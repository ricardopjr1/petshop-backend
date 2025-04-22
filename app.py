# --- START OF FILE app.py ---

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date
from flask_cors import CORS
from typing import List, Tuple, Dict, Any
import logging

load_dotenv()

# Configuração Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")

supabase: Client = create_client(url, key)

# Configuração Flask App e Logging
app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
app.logger.setLevel(logging.INFO)

# --- INÍCIO DA CONFIGURAÇÃO CORS ---

# URL EXATA do seu frontend deployado no Netlify
netlify_frontend_url = "https://effervescent-marshmallow-307a04.netlify.app"

# Outras origens que você pode precisar para desenvolvimento local (opcional)
local_dev_url_1 = "http://localhost:8000"
local_dev_url_2 = "http://127.0.0.1:5500"
# Adicione outras URLs se usar portas diferentes ou outros ambientes

allowed_origins = [
    netlify_frontend_url,  # <-- Essencial para o seu deploy Netlify
    local_dev_url_1,       # <-- Mantenha se desenvolver localmente
    local_dev_url_2,       # <-- Mantenha se desenvolver localmente com Live Server
    # "null"  # Remova ou comente 'null' - não é seguro e desnecessário para Netlify
]

# Imprime no log do servidor (visível na Vercel) para confirmar as origens carregadas
app.logger.info(f"--- CONFIGURAÇÃO CORS: Origens permitidas: {allowed_origins} ---")

# Aplica a configuração do CORS ao aplicativo Flask
CORS(app,
     origins=allowed_origins, # Lista de origens permitidas
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], # Métodos HTTP permitidos (incluir OPTIONS é importante)
     supports_credentials=True, # Permite envio de cookies/credenciais (se aplicável)
     expose_headers=["Content-Type", "Authorization"] # Cabeçalhos que o frontend pode acessar (ajuste se necessário)
)

# --- FIM DA CONFIGURAÇÃO CORS ---


# Mapeamento dias da semana
DIAS_SEMANA_PT = {
    0: 'Segunda-Feira',
    1: 'Terça-Feira',
    2: 'Quarta-Feira',
    3: 'Quinta-Feira',
    4: 'Sexta-Feira',
    5: 'Sábado',
    6: 'Domingo'
}


def parse_time(time_str: str) -> time | None:
    """Converte string de hora (HH:MM:SS ou HH:MM) para objeto time."""
    if not time_str: return None
    try:
        return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try:
            return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            app.logger.error(f"Formato de hora inválido recebido: {time_str}. Use HH:MM:SS ou HH:MM.")
            return None

def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    """Combina um objeto date e um objeto time em um objeto datetime."""
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)

def get_required_role_for_service(service_name: str) -> str | None:
    """Determina a função necessária para realizar UM serviço com base no nome."""
    if not service_name: return None
    service_name_lower = service_name.lower()
    if 'tosa' in service_name_lower:
        return 'Groomer'
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower or 'pelo' in service_name_lower:
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função específica para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'

def get_required_role_for_multiple_services(service_names: List[str]) -> str:
    """Determina a função MAIS EXIGENTE necessária para uma lista de serviços."""
    if not service_names:
        app.logger.warning("Lista de nomes de serviço vazia ao determinar função. Assumindo 'Banhista'.")
        return 'Banhista'
    contains_tosa = any('tosa' in name.lower() for name in service_names)
    if contains_tosa:
        app.logger.info("Pelo menos um serviço de 'tosa' detectado. Função requerida para o bloco: Groomer.")
        return 'Groomer'
    else:
        app.logger.info("Nenhum serviço de 'tosa' detectado. Função requerida para o bloco: Banhista.")
        return 'Banhista'


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """
    Busca e retorna os horários disponíveis para UM ou MÚLTIPLOS serviços
    em uma data específica. Para múltiplos, calcula a duração total e usa
    a função mais exigente (Groomer > Banhista).
    """
    try:
        app.logger.info(f"Recebida requisição GET para /api/horarios-disponiveis de {request.origin}") # Loga a origem

        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds')
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_ids_str or not empresa_id:
            app.logger.error(f"Erro 400: Parâmetros ausentes. data='{data_str}', servicoIds='{servico_ids_str}', empresaId='{empresa_id}'")
            return jsonify({"message": "Parâmetros 'data', 'servicoIds' e 'empresaId' são obrigatórios."}), 400

        try:
            servico_ids = [int(sid.strip()) for sid in servico_ids_str.split(',') if sid.strip().isdigit()]
            if not servico_ids:
                raise ValueError("Lista de IDs de serviço está vazia ou não contém números válidos.")
        except ValueError as e:
            app.logger.error(f"Erro 400: IDs de serviço inválidos '{servico_ids_str}'. {e}")
            return jsonify({"message": "Formato de IDs de serviço inválido. Use uma lista de números separados por vírgula (ex: 1,2,3)."}), 400

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro 400: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviços IDs: {servico_ids}")

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            app.logger.error(f"Erro 500: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500

        # Busca horários de funcionamento
        response_op_hours = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio')\
            .execute()

        if not response_op_hours.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404 # Not Found

        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response_op_hours.data:
             hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
             hora_fim_obj = parse_time(interval_data.get('hora_fim'))
             if hora_inicio_obj and hora_fim_obj and hora_fim_obj > hora_inicio_obj:
                 operating_intervals.append((hora_inicio_obj, hora_fim_obj))
                 app.logger.info(f"Intervalo de funcionamento válido: {hora_inicio_obj} - {hora_fim_obj}")
             else:
                 app.logger.warning(f"Intervalo de funcionamento inválido ignorado: {interval_data}.")

        if not operating_intervals:
              app.logger.error(f"Nenhum intervalo de funcionamento VÁLIDO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
              return jsonify({"message": f"Erro ao processar horários de funcionamento para {dia_semana_nome}."}), 500

        # Busca detalhes dos serviços solicitados
        response_services = supabase.table('servicos')\
            .select('id, tempo_servico, nome')\
            .in_('id', servico_ids)\
            .eq('empresa_id', empresa_id)\
            .execute()

        # Verifica se todos os serviços solicitados foram encontrados
        if not response_services.data or len(response_services.data) != len(servico_ids):
            found_ids = [s['id'] for s in response_services.data] if response_services.data else []
            missing_ids = list(set(servico_ids) - set(found_ids))
            app.logger.warning(f"Erro 404: Serviços não encontrados para a empresa {empresa_id}. Solicitados: {servico_ids}, Faltantes: {missing_ids}")
            return jsonify({"message": f"Um ou mais serviços selecionados não foram encontrados (IDs: {missing_ids})."}), 404 # Not Found

        # Calcula duração total e determina função requerida
        total_service_duration_minutes = 0
        service_names: List[str] = []
        for service_detail in response_services.data:
            try:
                duration = int(service_detail['tempo_servico'])
                if duration <= 0:
                    raise ValueError("Duração do serviço deve ser positiva.")
                total_service_duration_minutes += duration
                service_names.append(service_detail.get('nome', f"ID_{service_detail.get('id', '?')}"))
            except (ValueError, TypeError, KeyError) as e:
                 service_id_error = service_detail.get('id', 'N/A')
                 app.logger.error(f"Erro 500: Duração inválida para serviço ID {service_id_error}. Detalhe: {service_detail}. Erro: {e}")
                 return jsonify({"message": f"Duração inválida encontrada para o serviço ID {service_id_error}."}), 500

        required_role = get_required_role_for_multiple_services(service_names)
        app.logger.info(f"Serviços: {service_names}, Duração Total: {total_service_duration_minutes} min, Função Requerida: '{required_role}'")

        # Busca contagem de staff para a função requerida
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Profissionais '{required_role}' disponíveis: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Erro 404: Nenhum profissional '{required_role}' encontrado para empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais disponíveis ({required_role}) para realizar a combinação de serviços selecionada."}), 404 # Not Found

        # Busca agendamentos existentes na data
        response_appts = supabase.table('agendamentos')\
            .select('id, hora, servico') # Assume que 'servico' é o NOME do serviço
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()

        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Agendamentos existentes em {data_str}: {len(existing_appointments)}")

        # Calcula intervalos ocupados relevantes para a FUNÇÃO REQUERIDA
        role_specific_busy_intervals: List[Dict[str, datetime]] = []
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {} # Cache simples

        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento ID {appt_id} ignorado (dados incompletos).")
                continue

            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                resp_appt_svc = supabase.table('servicos')\
                    .select('tempo_servico, nome')\
                    .eq('empresa_id', empresa_id)\
                    .eq('nome', appt_service_name)\
                    .maybe_single()\
                    .execute()
                if not resp_appt_svc.data:
                    app.logger.warning(f"Detalhes do serviço '{appt_service_name}' (Agendamento {appt_id}) não encontrados. Ignorando para ocupação.")
                    continue
                appt_svc_details = resp_appt_svc.data
                appt_service_details_cache[appt_service_name] = appt_svc_details

            appt_existing_role = get_required_role_for_service(appt_svc_details.get('nome'))

            # Considera ocupado APENAS se a função do agendamento existente for a mesma requerida agora
            if appt_existing_role == required_role:
                try:
                    appt_duration = int(appt_svc_details['tempo_servico'])
                    if appt_duration <= 0: raise ValueError("Duração inválida")
                    appt_start_time_obj = parse_time(appt_time_str)
                    if appt_start_time_obj:
                        appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                        if not appt_start_dt: raise ValueError("Falha ao combinar data/hora")
                        appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                        role_specific_busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                    else:
                         app.logger.warning(f"Hora '{appt_time_str}' inválida para Agendamento {appt_id}. Ignorando.")
                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro processando Agendamento {appt_id} (Serviço: '{appt_service_name}'): {e}. Ignorando.")

        app.logger.info(f"Intervalos ocupados rastreados para '{required_role}': {len(role_specific_busy_intervals)}")

        # Calcula slots disponíveis
        available_slots: List[str] = []
        interval_minutes = 15 # Intervalo entre possíveis inícios

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)
            if not interval_start_dt or not interval_end_dt: continue # Segurança

            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            current_potential_dt = interval_start_dt

            while current_potential_dt <= last_possible_start_dt:
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                overlapping_count = 0
                for busy in role_specific_busy_intervals:
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1

                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))

                current_potential_dt += timedelta(minutes=interval_minutes)

        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"Horários disponíveis calculados para '{required_role}' ({total_service_duration_minutes} min) em {selected_date}: {len(unique_available_slots)}")
        app.logger.info(f"Slots: {unique_available_slots}")

        return jsonify(unique_available_slots) # Sucesso

    except Exception as e:
        app.logger.error(f"Erro 500: Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado no servidor. Tente novamente mais tarde."}), 500


# Rota de health check simples (opcional, mas útil)
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200


if __name__ == '__main__':
    # Obtém a porta da variável de ambiente PORT ou usa 5000 como padrão
    # Obtém o modo debug da variável de ambiente FLASK_DEBUG (true/false)
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == 'true'
    app.logger.info(f"Iniciando servidor Flask na porta {port} com debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FILE app.py ---

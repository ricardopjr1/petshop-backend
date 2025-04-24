# --- START OF FILE app.py ---

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date # Added datetime
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

# URLs dos seus frontends
netlify_frontend_url_old = "https://effervescent-marshmallow-307a04.netlify.app" # Mantida caso ainda use
netlify_frontend_url_new = "https://magenta-mandazi-f7d096.netlify.app"       # <<< NOVA URL ATUALIZADA

# Outras origens (desenvolvimento local)
local_dev_url_1 = "http://localhost:8000"
local_dev_url_2 = "http://127.0.0.1:5500"

# Lista atualizada de origens permitidas
allowed_origins = [
    netlify_frontend_url_old,
    netlify_frontend_url_new,  # <<< ADICIONADA A NOVA URL
    local_dev_url_1,
    local_dev_url_2,
]

app.logger.info(f"--- CONFIGURAÇÃO CORS: Origens permitidas: {allowed_origins} ---")

CORS(app,
     origins=allowed_origins, # Usa a lista atualizada
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"]
)
# --- FIM DA CONFIGURAÇÃO CORS ---


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
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower or 'pelo' in service_name_lower: # Ampliado
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista' # Default to Banhista if unsure

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
    (identificados por UUIDs como strings) em uma data específica,
    filtrando horários passados se a data for hoje.
    """
    try:
        app.logger.info(f"Recebida requisição GET para /api/horarios-disponiveis de {request.origin}")

        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds')
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_ids_str or not empresa_id:
            missing_params = []
            if not data_str: missing_params.append("'data'")
            if not servico_ids_str: missing_params.append("'servicoIds'")
            if not empresa_id: missing_params.append("'empresaId'")
            error_msg = f"Parâmetros obrigatórios ausentes: {', '.join(missing_params)}."
            app.logger.error(f"Erro 400: {error_msg} (data='{data_str}', servicoIds='{servico_ids_str}', empresaId='{empresa_id}')")
            return jsonify({"message": error_msg}), 400

        try:
            servico_ids_list = [sid.strip() for sid in servico_ids_str.split(',') if sid.strip()]
            if not servico_ids_list:
                raise ValueError("Lista de IDs de serviço resultou vazia após processamento.")
        except Exception as e:
             app.logger.error(f"Erro 400: Falha ao processar o parâmetro 'servicoIds' ('{servico_ids_str}'). Erro: {e}")
             return jsonify({"message": "Formato inválido para 'servicoIds'. Use UUIDs separados por vírgula."}), 400

        app.logger.info(f"IDs de serviço (UUIDs) a serem processados: {servico_ids_list}")

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro 400: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        # --- AJUSTE: Obter data e hora atuais ---
        now_dt = datetime.now()
        today_date = now_dt.date()
        current_time = now_dt.time()
        is_today = (selected_date == today_date)
        # --- FIM AJUSTE ---

        if selected_date < today_date:
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             # Mensagem já existente cobre isso.
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        # --- AJUSTE: Log informando se a filtragem por hora atual será aplicada ---
        if is_today:
            app.logger.info(f"Data selecionada ({selected_date}) é hoje. Horários anteriores a {current_time.strftime('%H:%M:%S')} serão filtrados.")
        else:
            app.logger.info(f"Data selecionada ({selected_date}) é futura. Não haverá filtragem por hora atual.")
        # --- FIM AJUSTE ---


        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviços IDs: {servico_ids_list}")

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome:
            app.logger.error(f"Erro 500: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500
        response_op_hours = supabase.table('horarios_funcionamento').select('hora_inicio, hora_fim').eq('empresa_id', empresa_id).eq('dia_semana', dia_semana_nome).eq('ativo', True).order('hora_inicio').execute()
        if not response_op_hours.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404
        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response_op_hours.data:
             hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
             hora_fim_obj = parse_time(interval_data.get('hora_fim'))
             if hora_inicio_obj and hora_fim_obj and hora_fim_obj > hora_inicio_obj:
                 operating_intervals.append((hora_inicio_obj, hora_fim_obj))
                 app.logger.info(f"Intervalo de funcionamento válido encontrado: {hora_inicio_obj} - {hora_fim_obj}")
             else:
                 app.logger.warning(f"Intervalo de funcionamento inválido ou mal formatado ignorado: {interval_data}.")
        if not operating_intervals:
              app.logger.error(f"Nenhum intervalo de funcionamento VÁLIDO encontrado para {dia_semana_nome} na empresa {empresa_id} após processamento.")
              return jsonify({"message": f"Erro ao processar horários de funcionamento para {dia_semana_nome}."}), 500

        response_services = supabase.table('servicos')\
            .select('id, tempo_servico, nome')\
            .in_('id', servico_ids_list)\
            .eq('empresa_id', empresa_id)\
            .execute()

        if not response_services.data or len(response_services.data) != len(servico_ids_list):
            found_ids = [s['id'] for s in response_services.data] if response_services.data else []
            missing_ids = list(set(servico_ids_list) - set(found_ids))
            app.logger.warning(f"Erro 404: Serviços não encontrados para a empresa {empresa_id}. Solicitados: {servico_ids_list}, Faltantes: {missing_ids}")
            return jsonify({"message": f"Um ou mais serviços selecionados não foram encontrados (IDs: {', '.join(missing_ids)})."}), 404

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

        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Total de profissionais '{required_role}' disponíveis na empresa: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{required_role}' encontrado para a empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais ({required_role}) disponíveis para realizar a combinação de serviços selecionada neste dia."}), 404

        response_appts = supabase.table('agendamentos')\
            .select('id, hora, servico')\
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()
        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Total de agendamentos encontrados na data {data_str}: {len(existing_appointments)}")

        role_specific_busy_intervals: List[Dict[str, datetime]] = []
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {}
        processed_appts_count = 0
        relevant_appts_count = 0

        for appt in existing_appointments:
            processed_appts_count += 1
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento ID {appt_id} com dados incompletos (hora ou serviço). Ignorando.")
                continue

            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
                if not resp_appt_svc.data:
                    app.logger.warning(f"Detalhes do serviço '{appt_service_name}' (Agendamento {appt_id}) não encontrados. Ignorando para ocupação.")
                    continue
                appt_svc_details = resp_appt_svc.data
                appt_service_details_cache[appt_service_name] = appt_svc_details

            appt_existing_role = get_required_role_for_service(appt_svc_details.get('nome'))

            if appt_existing_role == required_role:
                relevant_appts_count += 1
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
                         app.logger.warning(f"Não foi possível converter a hora '{appt_time_str}' do agendamento {appt_id}. Ignorando.")

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' ou hora '{appt_time_str}' para agendamento {appt_id}: {e}. Ignorando.")

        app.logger.info(f"Total de agendamentos processados: {processed_appts_count}. Agendamentos relevantes para '{required_role}': {relevant_appts_count}. Intervalos ocupados para '{required_role}': {len(role_specific_busy_intervals)}")

        available_slots: List[str] = []
        interval_minutes = 15

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)

            if not interval_start_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora para o intervalo {start_op_time}-{end_op_time}. Pulando intervalo.")
                continue

            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            current_potential_dt = interval_start_dt

            app.logger.info(f"Verificando slots no intervalo {interval_start_dt.time()} - {interval_end_dt.time()} (duração: {total_service_duration_minutes} min, último início: {last_possible_start_dt.time()})")

            while current_potential_dt <= last_possible_start_dt:
                # --- AJUSTE: Checar se o horário potencial já passou (APENAS SE FOR HOJE) ---
                if is_today and current_potential_dt.time() <= current_time:
                    # Log apenas na primeira vez ou com menos frequência se for muito verboso
                    # app.logger.debug(f"Pulando slot {current_potential_dt.strftime('%H:%M')} por ser anterior ou igual ao horário atual ({current_time.strftime('%H:%M:%S')}).")
                    current_potential_dt += timedelta(minutes=interval_minutes)
                    continue # Pula para a próxima iteração do while
                # --- FIM AJUSTE ---

                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                overlapping_count = 0
                for busy in role_specific_busy_intervals:
                    # Verifica sobreposição: O potencial começa antes do fim do ocupado E o potencial termina depois do início do ocupado
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1

                if overlapping_count < available_staff_count:
                    # Se não há profissionais suficientes ocupados naquele horário, o slot está disponível
                    available_slots.append(current_potential_dt.strftime('%H:%M'))
                    # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} adicionado. Ocupação: {overlapping_count}/{available_staff_count}")

                current_potential_dt += timedelta(minutes=interval_minutes)

        # A lista já contém apenas slots futuros se is_today for True, devido ao ajuste no loop
        unique_available_slots = sorted(list(set(available_slots)))

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{required_role}' (duração {total_service_duration_minutes} min) em {selected_date}: {len(unique_available_slots)}")
        app.logger.info(f"Slots calculados (após filtros): {unique_available_slots}") # Log final dos slots

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == 'true'
    app.logger.info(f"Iniciando servidor Flask na porta {port} com debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FILE app.py ---

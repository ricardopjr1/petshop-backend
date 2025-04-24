# --- START OF FILE app.py ---

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
# Importar datetime completo é importante aqui
from datetime import datetime, time, timedelta, date
from flask_cors import CORS
from typing import List, Tuple, Dict, Any
import logging
import math # Para arredondamento

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
netlify_frontend_url_old = "https://effervescent-marshmallow-307a04.netlify.app"
netlify_frontend_url_new = "https://magenta-mandazi-f7d096.netlify.app"
local_dev_url_1 = "http://localhost:8000"
local_dev_url_2 = "http://127.0.0.1:5500"
allowed_origins = [
    netlify_frontend_url_old,
    netlify_frontend_url_new,
    local_dev_url_1,
    local_dev_url_2,
]
app.logger.info(f"--- CONFIGURAÇÃO CORS: Origens permitidas: {allowed_origins} ---")
CORS(app,
     origins=allowed_origins,
     methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
     supports_credentials=True,
     expose_headers=["Content-Type", "Authorization"]
)
# --- FIM DA CONFIGURAÇÃO CORS ---

DIAS_SEMANA_PT = {
    0: 'Segunda-Feira', 1: 'Terça-Feira', 2: 'Quarta-Feira',
    3: 'Quinta-Feira', 4: 'Sexta-Feira', 5: 'Sábado', 6: 'Domingo'
}
INTERVALO_SLOT_MINUTOS = 15 # Definir como constante para facilitar ajuste

def parse_time(time_str: str) -> time | None:
    """Converte string de hora (HH:MM:SS ou HH:MM) para objeto time."""
    if not time_str: return None
    try: return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try: return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            app.logger.error(f"Formato de hora inválido: {time_str}. Use HH:MM:SS ou HH:MM.")
            return None

def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    """Combina um objeto date e um objeto time em um objeto datetime."""
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)

def get_required_role_for_service(service_name: str) -> str | None:
    """Determina a função necessária para UM serviço."""
    if not service_name: return None
    service_name_lower = service_name.lower()
    if 'tosa' in service_name_lower: return 'Groomer'
    elif any(term in service_name_lower for term in ['banho', 'hidratação', 'pelo']): return 'Banhista'
    app.logger.warning(f"Função não determinada para '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'

def get_required_role_for_multiple_services(service_names: List[str]) -> str:
    """Determina a função MAIS EXIGENTE para uma lista de serviços."""
    if not service_names: return 'Banhista'
    if any('tosa' in name.lower() for name in service_names): return 'Groomer'
    return 'Banhista'

@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """
    Busca e retorna os horários disponíveis para UM ou MÚLTIPLOS serviços
    em uma data específica, ajustando o ponto de partida para o dia atual.
    """
    try:
        app.logger.info(f"Recebida requisição GET para /api/horarios-disponiveis de {request.origin}")

        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds')
        empresa_id = request.args.get('empresaId')

        # Validação de parâmetros de entrada
        if not data_str or not servico_ids_str or not empresa_id:
            missing = [p for p, v in [('data', data_str), ('servicoIds', servico_ids_str), ('empresaId', empresa_id)] if not v]
            error_msg = f"Parâmetros obrigatórios ausentes: {', '.join(missing)}."
            app.logger.error(f"Erro 400: {error_msg}")
            return jsonify({"message": error_msg}), 400

        try:
            servico_ids_list = [sid.strip() for sid in servico_ids_str.split(',') if sid.strip()]
            if not servico_ids_list: raise ValueError("Lista de IDs vazia.")
        except Exception as e:
             app.logger.error(f"Erro 400: Falha ao processar 'servicoIds' ('{servico_ids_str}'). Erro: {e}")
             return jsonify({"message": "Formato inválido para 'servicoIds'."}), 400

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro 400: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        # --- AJUSTE PRINCIPAL: Lógica para hoje ---
        now_dt = datetime.now()
        today_date = now_dt.date()
        is_today = (selected_date == today_date)
        minimum_start_time_today = None

        if is_today:
            # Define a hora mínima para começar a procurar slots hoje.
            # Arredonda para o próximo intervalo de slot para simplificar.
            minutes_now = now_dt.hour * 60 + now_dt.minute
            # Calcula minutos até o início do próximo slot (ou o atual se já for múltiplo)
            minutes_to_next_slot_start = math.ceil(minutes_now / INTERVALO_SLOT_MINUTOS) * INTERVALO_SLOT_MINUTOS
            hour_next_slot = minutes_to_next_slot_start // 60
            minute_next_slot = minutes_to_next_slot_start % 60

            # Evita ir para o dia seguinte se o arredondamento passar das 23:59
            if hour_next_slot >= 24:
                 app.logger.warning("Cálculo do próximo slot ultrapassou a meia-noite. Nenhum slot disponível para hoje.")
                 return jsonify([]) # Retorna lista vazia se já passou do dia

            minimum_start_time_today = time(hour_next_slot, minute_next_slot)
            app.logger.info(f"Data é hoje ({selected_date}). Hora atual: {now_dt.strftime('%H:%M:%S')}. Slots serão considerados a partir de ~{minimum_start_time_today.strftime('%H:%M')}.")
        else:
            app.logger.info(f"Data selecionada ({selected_date}) é futura.")

        if selected_date < today_date:
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400
        # --- FIM AJUSTE PRINCIPAL ---

        app.logger.info(f"Buscando horários: Empresa={empresa_id}, Data={selected_date}, Serviços={servico_ids_list}")

        # Buscar Horário de Funcionamento
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome:
            app.logger.error(f"Erro 500: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500

        response_op_hours = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio')\
            .execute()

        if not response_op_hours.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404

        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response_op_hours.data:
             hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
             hora_fim_obj = parse_time(interval_data.get('hora_fim'))
             if hora_inicio_obj and hora_fim_obj and hora_fim_obj > hora_inicio_obj:
                 operating_intervals.append((hora_inicio_obj, hora_fim_obj))
             else:
                 app.logger.warning(f"Intervalo de funcionamento inválido ignorado: {interval_data}.")
        if not operating_intervals:
              app.logger.error(f"Nenhum intervalo de funcionamento VÁLIDO encontrado para {dia_semana_nome}, empresa {empresa_id}.")
              return jsonify({"message": f"Erro ao processar horários de funcionamento para {dia_semana_nome}."}), 500
        app.logger.info(f"Intervalos de funcionamento válidos: {operating_intervals}")

        # Buscar Detalhes dos Serviços e Calcular Duração Total
        response_services = supabase.table('servicos')\
            .select('id, tempo_servico, nome')\
            .in_('id', servico_ids_list)\
            .eq('empresa_id', empresa_id)\
            .execute()

        if not response_services.data or len(response_services.data) != len(servico_ids_list):
            found_ids = [s['id'] for s in response_services.data] if response_services.data else []
            missing_ids = list(set(servico_ids_list) - set(found_ids))
            app.logger.warning(f"Erro 404: Serviços não encontrados. Empresa: {empresa_id}. Solicitados: {servico_ids_list}, Faltantes: {missing_ids}")
            return jsonify({"message": f"Um ou mais serviços não foram encontrados (IDs: {', '.join(missing_ids)})."}), 404

        total_service_duration_minutes = 0
        service_names: List[str] = []
        for service_detail in response_services.data:
            try:
                duration = int(service_detail['tempo_servico'])
                if duration <= 0: raise ValueError("Duração não positiva.")
                total_service_duration_minutes += duration
                service_names.append(service_detail.get('nome', f"ID_{service_detail.get('id', '?')}"))
            except (ValueError, TypeError, KeyError) as e:
                 service_id_error = service_detail.get('id', 'N/A')
                 app.logger.error(f"Erro 500: Duração inválida serviço ID {service_id_error}. Detalhe: {service_detail}. Erro: {e}")
                 return jsonify({"message": f"Duração inválida para serviço ID {service_id_error}."}), 500

        required_role = get_required_role_for_multiple_services(service_names)
        app.logger.info(f"Serviços: {service_names}, Duração Total: {total_service_duration_minutes} min, Função: '{required_role}'")

        # Verificar Disponibilidade de Staff
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Profissionais '{required_role}' disponíveis: {available_staff_count}")
        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{required_role}' encontrado. Empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais ({required_role}) disponíveis para estes serviços."}), 404

        # Buscar Agendamentos Existentes
        response_appts = supabase.table('agendamentos')\
            .select('id, hora, servico')\
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()
        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Agendamentos existentes em {data_str}: {len(existing_appointments)}")

        # Processar Agendamentos para Intervalos Ocupados (pela função requerida)
        role_specific_busy_intervals: List[Dict[str, datetime]] = []
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {}
        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')
            if not appt_time_str or not appt_service_name: continue # Ignora dados incompletos

            # Cache para detalhes do serviço do agendamento
            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                # Atenção: Pode ser necessário buscar por ID se nomes não forem únicos
                resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
                if not resp_appt_svc.data:
                    app.logger.warning(f"Detalhes serviço '{appt_service_name}' (Agend. {appt_id}) não encontrados. Ignorando.")
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
                        if not appt_start_dt: raise ValueError("Combine falhou")
                        appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                        role_specific_busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro processando agend. {appt_id} (Serviço: '{appt_service_name}', Hora: '{appt_time_str}'): {e}. Ignorando.")

        app.logger.info(f"Intervalos ocupados por '{required_role}': {len(role_specific_busy_intervals)}")

        # Calcular Horários Disponíveis
        available_slots: List[str] = []

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)

            if not interval_start_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora p/ intervalo {start_op_time}-{end_op_time}.")
                continue

            # --- AJUSTE NO PONTO DE PARTIDA DO LOOP ---
            # Se for hoje, comece a verificar a partir do horário mínimo calculado ou do início do intervalo, o que for maior.
            current_potential_dt = interval_start_dt
            if is_today and minimum_start_time_today:
                 start_check_dt = combine_date_time(selected_date, minimum_start_time_today)
                 if start_check_dt and start_check_dt > current_potential_dt:
                     current_potential_dt = start_check_dt
                     app.logger.info(f"Ajustando início da verificação para {current_potential_dt.strftime('%H:%M')} devido à hora atual.")
            # --- FIM AJUSTE ---


            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            app.logger.info(f"Verificando {start_op_time}-{end_op_time}. Duração={total_service_duration_minutes}min. Início real da verificação={current_potential_dt.strftime('%H:%M')}. Último início possível={last_possible_start_dt.strftime('%H:%M')}")


            while current_potential_dt <= last_possible_start_dt:
                # Garante que o horário potencial não comece *antes* do horário de funcionamento (caso o ajuste o tenha movido para trás)
                # E também garante que não comecemos antes do horário de abertura do intervalo atual
                if current_potential_dt < interval_start_dt:
                    current_potential_dt = interval_start_dt # Reset se necessário (pouco provável com a lógica atual)

                # Se ainda assim, após ajustes, for antes do mínimo para hoje, avançar
                if is_today and minimum_start_time_today and current_potential_dt.time() < minimum_start_time_today:
                   # Avança para o próximo slot alinhado com o intervalo
                   minutes_current = current_potential_dt.hour * 60 + current_potential_dt.minute
                   minutes_to_next_start = math.ceil(minutes_current / INTERVALO_SLOT_MINUTOS) * INTERVALO_SLOT_MINUTOS
                   hour_next = minutes_to_next_start // 60
                   minute_next = minutes_to_next_start % 60
                   if hour_next >= 24: break # Sai do loop se passar do dia
                   current_potential_dt = current_potential_dt.replace(hour=hour_next, minute=minute_next, second=0, microsecond=0)
                   continue # Reavalia no próximo ciclo do while


                # Verifica se o slot inteiro cabe antes do fim do intervalo de operação
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)
                if potential_end_dt > interval_end_dt:
                    # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} ({total_service_duration_minutes} min) ultrapassa fim do intervalo {interval_end_dt.strftime('%H:%M')}. Pulando para próximo intervalo.")
                    break # Não cabe mais neste intervalo de operação

                # Contagem de sobreposições com agendamentos da mesma função
                overlapping_count = 0
                for busy in role_specific_busy_intervals:
                    # Verifica sobreposição (início < fim_ocupado E fim > inicio_ocupado)
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1
                        # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} sobrepõe com {busy['start'].strftime('%H:%M')}-{busy['end'].strftime('%H:%M')}")


                # Verifica se há staff suficiente disponível
                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))
                    # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} adicionado. Ocupação: {overlapping_count}/{available_staff_count}")
                # else:
                    # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} indisponível. Ocupação: {overlapping_count}/{available_staff_count}")


                # Avança para o próximo slot potencial
                current_potential_dt += timedelta(minutes=INTERVALO_SLOT_MINUTOS)


        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"Total de horários disponíveis únicos calculados: {len(unique_available_slots)}")
        app.logger.info(f"Slots calculados: {unique_available_slots}")

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado em /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Erro interno inesperado. Tente novamente."}), 500

@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    debug_mode = os.environ.get("FLASK_DEBUG", "false").lower() == 'true'
    app.logger.info(f"Iniciando servidor Flask na porta {port} com debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FILE app.py ---

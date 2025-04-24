# --- START OF FILE app.py ---

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date, timezone
from flask_cors import CORS
from typing import List, Tuple, Dict, Any
import logging
import math

load_dotenv()

# Configuração Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas.")

supabase: Client = create_client(url, key)

# Configuração Flask App e Logging
app = Flask(__name__)
# Configurar para mostrar DEBUG. Em produção, você pode querer INFO.
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s:%(lineno)d: %(message)s')
app.logger.setLevel(logging.DEBUG) # Garante que o logger do app também use DEBUG

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
INTERVALO_SLOT_MINUTOS = 15

def parse_time(time_str: str) -> time | None:
    """Converte string HH:MM:SS ou HH:MM para objeto time."""
    if not time_str: return None
    for fmt in ('%H:%M:%S', '%H:%M'):
        try: return datetime.strptime(time_str, fmt).time()
        except ValueError: pass
    app.logger.error(f"Formato de hora inválido: {time_str}.")
    return None

def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    """Combina date e time em datetime (naive)."""
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)

def get_required_role_for_service(service_name: str) -> str | None:
    """Determina função para UM serviço."""
    if not service_name: return None
    service_name_lower = service_name.lower()
    if 'tosa' in service_name_lower: return 'Groomer'
    elif any(term in service_name_lower for term in ['banho', 'hidratação', 'pelo']): return 'Banhista'
    app.logger.warning(f"Função não determinada para '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'

def get_required_role_for_multiple_services(service_names: List[str]) -> str:
    """Determina função MAIS EXIGENTE para múltiplos serviços."""
    if not service_names: return 'Banhista'
    if any('tosa' in name.lower() for name in service_names):
         app.logger.debug("Função requerida para bloco: Groomer (devido a Tosa)")
         return 'Groomer'
    app.logger.debug("Função requerida para bloco: Banhista")
    return 'Banhista'

@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """
    Busca horários disponíveis, com logging detalhado para diagnóstico.
    """
    try:
        app.logger.info(f"Requisição GET /api/horarios-disponiveis de {request.origin}")
        # ... (validação de parâmetros igual a antes) ...
        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds')
        empresa_id = request.args.get('empresaId')
        if not data_str or not servico_ids_str or not empresa_id:
            missing = [p for p, v in [('data', data_str), ('servicoIds', servico_ids_str), ('empresaId', empresa_id)] if not v]
            error_msg = f"Parâmetros obrigatórios ausentes: {', '.join(missing)}."
            app.logger.error(f"Erro 400: {error_msg}")
            return jsonify({"message": error_msg}), 400
        try:
            servico_ids_list = [sid.strip() for sid in servico_ids_str.split(',') if sid.strip()]
            if not servico_ids_list: raise ValueError("Lista de IDs vazia.")
        except Exception as e:
             app.logger.error(f"Erro 400: Falha processar 'servicoIds'('{servico_ids_str}'). Erro: {e}")
             return jsonify({"message": "Formato inválido para 'servicoIds'."}), 400
        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro 400: Formato data inválido '{data_str}'.")
            return jsonify({"message": "Formato data inválido. Use YYYY-MM-DD."}), 400

        # Lógica "AGORA"
        now_dt_local = datetime.now()
        today_date = now_dt_local.date()
        is_today = (selected_date == today_date)
        minimum_start_dt_today = None
        if is_today:
            minimum_start_dt_today = now_dt_local
            app.logger.info(f"Data é hoje ({selected_date}). Hora atual: {now_dt_local.strftime('%H:%M:%S')}.")
        else:
            app.logger.info(f"Data selecionada ({selected_date}) é futura.")
        if selected_date < today_date:
             app.logger.warning(f"Data passada ({selected_date}) solicitada.")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários: Empresa={empresa_id}, Data={selected_date}, Serviços={servico_ids_list}")

        # Horário de Funcionamento
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome: return jsonify({"message": "Erro interno dia semana."}), 500
        response_op_hours = supabase.table('horarios_funcionamento').select('hora_inicio, hora_fim').eq('empresa_id', empresa_id).eq('dia_semana', dia_semana_nome).eq('ativo', True).order('hora_inicio').execute()
        if not response_op_hours.data: return jsonify({"message": f"Petshop fechado/sem horário para {dia_semana_nome}."}), 404
        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response_op_hours.data:
             hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
             hora_fim_obj = parse_time(interval_data.get('hora_fim'))
             if hora_inicio_obj and hora_fim_obj and hora_fim_obj > hora_inicio_obj: operating_intervals.append((hora_inicio_obj, hora_fim_obj))
             else: app.logger.warning(f"Intervalo inválido ignorado: {interval_data}.")
        if not operating_intervals: return jsonify({"message": f"Erro processar horários para {dia_semana_nome}."}), 500
        app.logger.info(f"Intervalos de funcionamento encontrados: {operating_intervals}") # LOG IMPORTANTE

        # Detalhes dos Serviços e Duração Total
        # ... (busca de serviços igual a antes) ...
        response_services = supabase.table('servicos').select('id, tempo_servico, nome').in_('id', servico_ids_list).eq('empresa_id', empresa_id).execute()
        if not response_services.data or len(response_services.data) != len(servico_ids_list):
            found_ids = [s['id'] for s in response_services.data] if response_services.data else []
            missing_ids = list(set(servico_ids_list) - set(found_ids))
            app.logger.warning(f"Erro 404: Serviços não encontrados. IDs: {missing_ids}")
            return jsonify({"message": f"Serviços não encontrados (IDs: {', '.join(missing_ids)})."}), 404
        total_service_duration_minutes = 0
        service_names: List[str] = []
        for sd in response_services.data:
             try:
                 duration = int(sd['tempo_servico'])
                 if duration <= 0: raise ValueError("Duração não positiva.")
                 total_service_duration_minutes += duration
                 service_names.append(sd.get('nome', f"ID_{sd.get('id', '?')}"))
             except (ValueError, TypeError, KeyError) as e:
                  sid_err = sd.get('id', 'N/A')
                  app.logger.error(f"Erro 500: Duração inválida serv ID {sid_err}. Erro: {e}")
                  return jsonify({"message": f"Duração inválida serv ID {sid_err}."}), 500

        required_role = get_required_role_for_multiple_services(service_names)
        app.logger.info(f"Serviços: {service_names}, Duração Total: {total_service_duration_minutes} min, Função Req: '{required_role}'")

        # Disponibilidade de Staff
        response_staff = supabase.table('usuarios').select('id', count='exact').eq('empresa_id', empresa_id).eq('funcao', required_role).execute()
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"===> Profissionais '{required_role}' disponíveis TOTAL: {available_staff_count} <===") # LOG IMPORTANTE
        if available_staff_count == 0: return jsonify({"message": f"Não há profissionais ({required_role}) disponíveis."}), 404

        # Agendamentos Existentes
        response_appts = supabase.table('agendamentos').select('id, hora, servico').eq('empresa_id', empresa_id).eq('data', data_str).execute()
        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Agendamentos existentes em {data_str}: {len(existing_appointments)}")

        # Processar Agendamentos para Intervalos Ocupados
        role_specific_busy_intervals: List[Dict[str, Any]] = []
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {}

        app.logger.debug(f"--- Calculando Intervalos Ocupados para role '{required_role}' ---")
        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')
            if not appt_time_str or not appt_service_name: continue

            # Cache detalhes do serviço
            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
                if not resp_appt_svc.data:
                    app.logger.warning(f"Detalhes serv '{appt_service_name}' (Agend. {appt_id}) não encontrados.")
                    continue
                appt_svc_details = resp_appt_svc.data
                appt_service_details_cache[appt_service_name] = appt_svc_details

            appt_existing_role = get_required_role_for_service(appt_svc_details.get('nome'))
            app.logger.debug(f"  Agend ID {appt_id}: Serv='{appt_service_name}', Hora='{appt_time_str}', Role Req para ele='{appt_existing_role}'")

            if appt_existing_role == required_role:
                try:
                    appt_duration = int(appt_svc_details['tempo_servico'])
                    if appt_duration <= 0: raise ValueError("Duração inválida")
                    appt_start_time_obj = parse_time(appt_time_str)
                    if not appt_start_time_obj: raise ValueError(f"Hora inválida: {appt_time_str}")

                    scheduled_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                    if not scheduled_start_dt: raise ValueError("Combine falhou")
                    scheduled_end_dt = scheduled_start_dt + timedelta(minutes=appt_duration)

                    busy_interval = {'start': scheduled_start_dt, 'end': scheduled_end_dt, 'id': appt_id}
                    role_specific_busy_intervals.append(busy_interval)
                    app.logger.info(f"    => Intervalo OCUPADO adicionado para '{required_role}': ID={appt_id}, Start={scheduled_start_dt.strftime('%H:%M')}, End={scheduled_end_dt.strftime('%H:%M')}") # LOG IMPORTANTE

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"    Erro processando agend. {appt_id}: {e}. Ignorando.")
        app.logger.debug(f"--- Fim Cálculo Intervalos Ocupados. Total para '{required_role}': {len(role_specific_busy_intervals)} ---")


        # Calcular Horários Disponíveis
        available_slots: List[str] = []

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)
            if not interval_start_dt or not interval_end_dt: continue

            app.logger.debug(f"\n--- Verificando Intervalo Operacional: {start_op_time} - {end_op_time} ---")

            # AJUSTE PONTO DE PARTIDA "AGORA"
            current_potential_dt = interval_start_dt
            start_log_msg = f"Iniciando verificação em {current_potential_dt.strftime('%H:%M')}"
            if is_today and minimum_start_dt_today and minimum_start_dt_today > current_potential_dt:
                current_potential_dt = minimum_start_dt_today
                minutes_since_midnight = current_potential_dt.hour * 60 + current_potential_dt.minute
                start_minute_block = math.floor(minutes_since_midnight / INTERVALO_SLOT_MINUTOS) * INTERVALO_SLOT_MINUTOS
                hour_aligned = start_minute_block // 60
                minute_aligned = start_minute_block % 60
                aligned_dt = current_potential_dt.replace(hour=hour_aligned, minute=minute_aligned, second=0, microsecond=0)
                if aligned_dt < current_potential_dt:
                    aligned_dt += timedelta(minutes=INTERVALO_SLOT_MINUTOS)
                current_potential_dt = aligned_dt
                start_log_msg = f"Ajustando início da verificação para slot >= {current_potential_dt.strftime('%H:%M')} devido à hora atual."

            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            app.logger.info(f"Intervalo {start_op_time}-{end_op_time}. {start_log_msg}. Duração={total_service_duration_minutes}min. Último início={last_possible_start_dt.strftime('%H:%M')}")

            # Loop principal de verificação de slots
            while current_potential_dt <= last_possible_start_dt:
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)
                app.logger.debug(f"  ? Testando Slot: {current_potential_dt.strftime('%H:%M')} -> {potential_end_dt.strftime('%H:%M')}")

                # Garantias de estar dentro do intervalo atual
                if current_potential_dt < interval_start_dt: current_potential_dt = interval_start_dt
                if potential_end_dt > interval_end_dt:
                    app.logger.debug(f"    ! Slot excede fim do intervalo ({interval_end_dt.strftime('%H:%M')}). Parando.")
                    break

                # Contagem de sobreposições
                overlapping_count = 0
                overlapping_ids = [] # Para log
                for busy in role_specific_busy_intervals:
                    busy_start_compare = busy['start']
                    busy_end_compare = busy['end']
                    potential_start_compare = current_potential_dt
                    potential_end_compare = potential_end_dt

                    # Verifica sobreposição
                    if potential_start_compare < busy_end_compare and potential_end_compare > busy_start_compare:
                        overlapping_count += 1
                        overlapping_ids.append(busy['id'])
                        app.logger.debug(f"    * COLISÃO detectada com Agend. ID={busy['id']} ({busy_start_compare.strftime('%H:%M')}-{busy_end_compare.strftime('%H:%M')})")

                # Decisão: Slot disponível ou não?
                app.logger.debug(f"    Contagem de Colisões: {overlapping_count}. Staff Disponível: {available_staff_count}")
                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))
                    app.logger.info(f"    ===> SLOT DISPONÍVEL: {current_potential_dt.strftime('%H:%M')} (Colisões: {overlapping_count} < Staff: {available_staff_count})") # LOG IMPORTANTE
                else:
                     app.logger.debug(f"    --- SLOT BLOQUEADO: {current_potential_dt.strftime('%H:%M')} (Colisões: {overlapping_count} >= Staff: {available_staff_count}). Agends conflitantes: {overlapping_ids}") # LOG IMPORTANTE

                # Avança para o próximo slot potencial
                current_potential_dt += timedelta(minutes=INTERVALO_SLOT_MINUTOS)

            app.logger.debug(f"--- Fim da verificação para {start_op_time} - {end_op_time} ---")


        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"\nTotal de horários disponíveis únicos calculados: {len(unique_available_slots)}")
        app.logger.info(f"===> Slots finais retornados: {unique_available_slots} <===") # LOG IMPORTANTE

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado em /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Erro interno inesperado. Tente novamente."}), 500

# ... (health_check e __main__ iguais a antes) ...
@app.route('/health', methods=['GET'])
def health_check():
    return jsonify({"status": "ok"}), 200

if __name__ == '__main__':
    port = int(os.environ.get("PORT", 5000))
    # Forçar modo DEBUG para garantir logs detalhados
    debug_mode = True # os.environ.get("FLASK_DEBUG", "false").lower() == 'true'
    app.logger.info(f"Iniciando servidor Flask na porta {port} com debug={debug_mode}")
    # Rodar com debug=True força o logger para DEBUG também
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FILE app.py ---

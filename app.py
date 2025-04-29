# --- START OF FILE app.py ---

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
# IMPORTANTE: Adicionar zoneinfo e timezone
from datetime import datetime, time, timedelta, date, timezone
try:
    from zoneinfo import ZoneInfo
except ImportError:
    # Fallback para pytz se zoneinfo não estiver disponível (Python < 3.9)
    try:
        import pytz
        # Monkey patch ZoneInfo se necessário (ou use pytz diretamente)
        class ZoneInfo:
             def __init__(self, key):
                 self._tz = pytz.timezone(key)
             def localize(self, dt): # Método similar ao pytz
                 return self._tz.localize(dt)
             # Adicionar outros métodos conforme necessário ou usar _tz diretamente
    except ImportError:
        app.logger.critical("Biblioteca de timezone (zoneinfo ou pytz) não encontrada!")
        # Você pode querer lançar um erro aqui ou ter um fallback muito básico
        ZoneInfo = None # Define como None para indicar falha


from flask_cors import CORS
from typing import List, Tuple, Dict, Any
import logging
import math

load_dotenv()

# Configuração Supabase
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
if not url or not key: raise EnvironmentError("SUPABASE_URL/KEY não encontradas.")
supabase: Client = create_client(url, key)

# Configuração Flask App e Logging
app = Flask(__name__)
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s:%(lineno)d: %(message)s')
app.logger.setLevel(logging.DEBUG)

# --- FUSO HORÁRIO ---
# Define o fuso horário de São Paulo
try:
    SAO_PAULO_TZ = ZoneInfo("America/Sao_Paulo")
    app.logger.info(f"Fuso horário configurado: America/Sao_Paulo usando zoneinfo.")
except Exception as e:
    app.logger.error(f"Falha ao carregar ZoneInfo('America/Sao_Paulo'): {e}. Tentando UTC como fallback.")
    # Fallback MUITO básico se tudo falhar - pode não ser ideal
    SAO_PAULO_TZ = timezone.utc


# --- CORS ---
# ... (configuração CORS igual a antes) ...
netlify_frontend_url_old = "https://effervescent-marshmallow-307a04.netlify.app"
netlify_frontend_url_new = "https://magenta-mandazi-f7d096.netlify.app"
local_dev_url_1 = "http://localhost:8000"
local_dev_url_2 = "http://127.0.0.1:5500"
allowed_origins = [ netlify_frontend_url_old, netlify_frontend_url_new, local_dev_url_1, local_dev_url_2 ]
app.logger.info(f"--- CORS: Origens permitidas: {allowed_origins} ---")
CORS(app, origins=allowed_origins, methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"], supports_credentials=True, expose_headers=["Content-Type", "Authorization"])
# --- FIM CORS ---

DIAS_SEMANA_PT = { 0: 'Segunda-Feira', 1: 'Terça-Feira', 2: 'Quarta-Feira', 3: 'Quinta-Feira', 4: 'Sexta-Feira', 5: 'Sábado', 6: 'Domingo' }
INTERVALO_SLOT_MINUTOS = 15

def parse_time(time_str: str) -> time | None:
    """Converte string HH:MM:SS ou HH:MM para objeto time."""
    if not time_str: return None
    for fmt in ('%H:%M:%S', '%H:%M'):
        try: return datetime.strptime(time_str, fmt).time()
        except ValueError: pass
    app.logger.error(f"Formato de hora inválido: {time_str}.")
    return None

# --- ATUALIZAÇÃO: combine_date_time para criar datetime AWARE ---
def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    """Combina date e time em datetime AWARE (fuso de São Paulo)."""
    if not data_obj or not tempo_obj: return None
    try:
        # Cria datetime AWARE diretamente usando o fuso horário definido
        return datetime.combine(data_obj, tempo_obj, tzinfo=SAO_PAULO_TZ)
    except Exception as e:
        app.logger.error(f"Erro ao combinar data/hora com timezone: Data={data_obj}, Tempo={tempo_obj}, Erro={e}")
        # Fallback para naive pode causar TypeErrors depois, mas evita crash aqui
        return datetime.combine(data_obj, tempo_obj)


def get_required_role_for_service(service_name: str) -> str | None:
    """Determina função para UM serviço."""
    # ... (igual a antes) ...
    if not service_name: return None
    service_name_lower = service_name.lower()
    if 'tosa' in service_name_lower: return 'Banho e Tosa'
    elif any(term in service_name_lower for term in ['banho', 'hidratação', 'pelo']): return 'Banho e Tosa'
    app.logger.warning(f"Função não determinada para '{service_name}'. Assumindo 'Banho e Tosa'.")
    return 'Banho e Tosa'

def get_required_role_for_multiple_services(service_names: List[str]) -> str:
    """Determina função MAIS EXIGENTE para múltiplos serviços."""
    # ... (igual a antes) ...
    if not service_names: return 'Banho e Tosa'
    if any('tosa' in name.lower() for name in service_names):
         app.logger.debug("Função requerida para bloco: Banho e Tosa (devido a Tosa)")
         return 'Banho e Tosa'
    app.logger.debug("Função requerida para bloco: Banho e Tosa")
    return 'Banho e Tosa'


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """
    Busca horários disponíveis, usando fuso horário de São Paulo para 'agora'.
    """
    try:
        # ... (obter parâmetros igual a antes) ...
        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds')
        empresa_id = request.args.get('empresaId')
        # ... (validação de parâmetros igual a antes) ...
        if not data_str or not servico_ids_str or not empresa_id:
             missing = [p for p,v in [('data',data_str),('servicoIds',servico_ids_str),('empresaId',empresa_id)] if not v]
             return jsonify({"message": f"Ausentes: {', '.join(missing)}"}), 400
        try:
            servico_ids_list = [s.strip() for s in servico_ids_str.split(',') if s.strip()]
            if not servico_ids_list: raise ValueError("IDs vazios")
        except Exception as e: return jsonify({"message": "servicoIds inválido"}), 400
        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError: return jsonify({"message": "Formato data inválido"}), 400


        # --- ATUALIZAÇÃO: Obter "agora" no fuso de São Paulo ---
        now_dt_local = datetime.now(SAO_PAULO_TZ)
        today_date = now_dt_local.date() # Data local de SP
        is_today = (selected_date == today_date)
        minimum_start_dt_today = None

        app.logger.info(f"HORA ATUAL ({(SAO_PAULO_TZ or 'N/A')}): {now_dt_local.strftime('%Y-%m-%d %H:%M:%S %Z%z')}")

        if is_today:
            minimum_start_dt_today = now_dt_local # AGORA é aware
            app.logger.info(f"Data é hoje ({selected_date}). Verificação iniciará considerando a hora atual (SP).")
        else:
            app.logger.info(f"Data selecionada ({selected_date}) é futura.")

        if selected_date < today_date:
             app.logger.warning(f"Data passada ({selected_date}) solicitada.")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400
        # --- FIM ATUALIZAÇÃO ---

        app.logger.info(f"Buscando horários: Emp={empresa_id}, Data={selected_date}, Serv={servico_ids_list}")

        # Horário de Funcionamento (sem mudanças na lógica, mas combine_date_time agora retorna aware)
        # ... (igual a antes) ...
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome: return jsonify({"message": "Erro dia semana"}), 500
        response_op_hours = supabase.table('horarios_funcionamento').select('hora_inicio, hora_fim').eq('empresa_id', empresa_id).eq('dia_semana', dia_semana_nome).eq('ativo', True).order('hora_inicio').execute()
        if not response_op_hours.data: return jsonify({"message": f"Fechado/sem horário {dia_semana_nome}"}), 404
        operating_intervals: List[Tuple[time, time]] = []
        for d in response_op_hours.data:
            hi = parse_time(d.get('hora_inicio'))
            hf = parse_time(d.get('hora_fim'))
            if hi and hf and hf > hi: operating_intervals.append((hi, hf))
            else: app.logger.warning(f"Intervalo inválido: {d}")
        if not operating_intervals: return jsonify({"message": f"Erro horários {dia_semana_nome}"}), 500
        app.logger.info(f"Intervalos funcionamento: {operating_intervals}")


        # Detalhes dos Serviços (sem mudanças)
        # ... (igual a antes) ...
        response_services = supabase.table('servicos').select('id, tempo_servico, nome').in_('id', servico_ids_list).eq('empresa_id', empresa_id).execute()
        if not response_services.data or len(response_services.data) != len(servico_ids_list):
             missing_ids = list(set(servico_ids_list) - set([s['id'] for s in response_services.data or []]))
             return jsonify({"message": f"Serviços não encontrados: {missing_ids}"}), 404
        total_service_duration_minutes = 0
        service_names = []
        for sd in response_services.data:
            try:
                dur = int(sd['tempo_servico'])
                if dur <= 0: raise ValueError("Duração inválida")
                total_service_duration_minutes += dur
                service_names.append(sd.get('nome', f"ID_{sd.get('id','?')}"))
            except Exception as e: return jsonify({"message": f"Duração inválida serv ID {sd.get('id','N/A')}"}), 500
        required_role = get_required_role_for_multiple_services(service_names)
        app.logger.info(f"Servs:{service_names}, Duração:{total_service_duration_minutes}m, Role:'{required_role}'")


        # Disponibilidade de Staff (sem mudanças)
        # ... (igual a antes) ...
        response_staff=supabase.table('usuarios').select('id',count='exact').eq('empresa_id',empresa_id).eq('funcao',required_role).execute()
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"===> Staff '{required_role}' TOTAL: {available_staff_count} <===")
        if available_staff_count == 0: return jsonify({"message": f"Sem staff ({required_role}) disponível."}), 404


        # Agendamentos Existentes (sem mudanças na busca)
        # ... (igual a antes) ...
        response_appts = supabase.table('agendamentos').select('id, hora, servico').eq('empresa_id', empresa_id).eq('data', data_str).execute()
        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Agends existentes em {data_str}: {len(existing_appointments)}")


        # Processar Agendamentos (combine_date_time agora retorna aware)
        role_specific_busy_intervals: List[Dict[str, Any]] = []
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {}
        app.logger.debug(f"--- Calculando Intervalos Ocupados (Aware) para role '{required_role}' ---")
        for appt in existing_appointments:
            # ... (lógica interna igual a antes, mas scheduled_start/end_dt agora são AWARE) ...
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')
            if not appt_time_str or not appt_service_name: continue

            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
                if not resp_appt_svc.data: continue
                appt_svc_details = resp_appt_svc.data
                appt_service_details_cache[appt_service_name] = appt_svc_details

            appt_existing_role = get_required_role_for_service(appt_svc_details.get('nome'))
            app.logger.debug(f"  Agend ID {appt_id}: Serv='{appt_service_name}', Hora='{appt_time_str}', Role Req='{appt_existing_role}'")

            if appt_existing_role == required_role:
                try:
                    appt_duration = int(appt_svc_details['tempo_servico'])
                    if appt_duration <= 0: raise ValueError("Duração inválida")
                    appt_start_time_obj = parse_time(appt_time_str)
                    if not appt_start_time_obj: raise ValueError(f"Hora inválida: {appt_time_str}")

                    # ESTES DATETIMES AGORA SÃO AWARE (SP TZ)
                    scheduled_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                    if not scheduled_start_dt: raise ValueError("Combine falhou")
                    scheduled_end_dt = scheduled_start_dt + timedelta(minutes=appt_duration)

                    busy_interval = {'start': scheduled_start_dt, 'end': scheduled_end_dt, 'id': appt_id}
                    role_specific_busy_intervals.append(busy_interval)
                    # Log formatado para mostrar timezone
                    start_fmt = scheduled_start_dt.strftime('%H:%M %Z%z')
                    end_fmt = scheduled_end_dt.strftime('%H:%M %Z%z')
                    app.logger.info(f"    => Intervalo OCUPADO (Aware) adicionado: ID={appt_id}, Start={start_fmt}, End={end_fmt}")

                except Exception as e: # Captura mais genérica por causa do combine
                    app.logger.warning(f"    Erro processando agend. {appt_id}: {e}. Ignorando.")

        app.logger.debug(f"--- Fim Cálculo Intervalos Ocupados (Aware). Total: {len(role_specific_busy_intervals)} ---")


        # Calcular Horários Disponíveis (Comparações agora são Aware vs Aware)
        available_slots: List[str] = []
        for start_op_time, end_op_time in operating_intervals:
            # ESTES DATETIMES AGORA SÃO AWARE (SP TZ)
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)
            if not interval_start_dt or not interval_end_dt: continue

            app.logger.debug(f"\n--- Verificando Intervalo Operacional (Aware): {start_op_time} - {end_op_time} ---")

            # AJUSTE PONTO DE PARTIDA "AGORA" (Aware)
            current_potential_dt = interval_start_dt # Aware
            start_log_msg = f"Iniciando verificação em {current_potential_dt.strftime('%H:%M %Z')}"
            if is_today and minimum_start_dt_today and minimum_start_dt_today > current_potential_dt:
                current_potential_dt = minimum_start_dt_today # Aware
                # Arredondamento (lógica mantida, opera sobre aware dt)
                minutes_since_midnight = current_potential_dt.hour * 60 + current_potential_dt.minute
                start_minute_block = math.floor(minutes_since_midnight / INTERVALO_SLOT_MINUTOS) * INTERVALO_SLOT_MINUTOS
                hour_aligned = start_minute_block // 60
                minute_aligned = start_minute_block % 60
                # Cria novo datetime AWARE alinhado
                aligned_dt = current_potential_dt.replace(hour=hour_aligned, minute=minute_aligned, second=0, microsecond=0)
                if aligned_dt < current_potential_dt:
                    aligned_dt += timedelta(minutes=INTERVALO_SLOT_MINUTOS)
                current_potential_dt = aligned_dt
                start_log_msg = f"Ajustando início (Aware) para slot >= {current_potential_dt.strftime('%H:%M %Z')} devido à hora atual."

            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes) # Aware
            app.logger.info(f"Int {start_op_time}-{end_op_time}. {start_log_msg}. Duração={total_service_duration_minutes}m. Último início={last_possible_start_dt.strftime('%H:%M %Z')}")

            # Loop principal (Comparações Aware)
            while current_potential_dt <= last_possible_start_dt:
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes) # Aware
                app.logger.debug(f"  ? Testando Slot (Aware): {current_potential_dt.strftime('%H:%M %Z')} -> {potential_end_dt.strftime('%H:%M %Z')}")

                if current_potential_dt < interval_start_dt: current_potential_dt = interval_start_dt
                if potential_end_dt > interval_end_dt:
                    app.logger.debug(f"    ! Slot excede fim {interval_end_dt.strftime('%H:%M %Z')}. Parando.")
                    break

                # Contagem de sobreposições (Aware vs Aware)
                overlapping_count = 0
                overlapping_ids = []
                for busy in role_specific_busy_intervals:
                    # Comparação direta de datetimes aware funciona corretamente
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1
                        overlapping_ids.append(busy['id'])
                        app.logger.debug(f"    * COLISÃO (Aware) com Agend ID={busy['id']} ({busy['start'].strftime('%H:%M %Z')}-{busy['end'].strftime('%H:%M %Z')})")

                app.logger.debug(f"    Contagem Colisões: {overlapping_count}. Staff: {available_staff_count}")
                if overlapping_count < available_staff_count:
                    # Armazena apenas a string HH:MM para o frontend
                    available_slots.append(current_potential_dt.strftime('%H:%M'))
                    app.logger.info(f"    ===> SLOT DISPONÍVEL: {current_potential_dt.strftime('%H:%M %Z')} (Colisões: {overlapping_count} < Staff: {available_staff_count})")
                else:
                     app.logger.debug(f"    --- SLOT BLOQUEADO: {current_potential_dt.strftime('%H:%M %Z')} (Colisões: {overlapping_count} >= Staff: {available_staff_count}). Agends: {overlapping_ids}")

                current_potential_dt += timedelta(minutes=INTERVALO_SLOT_MINUTOS) # timedelta funciona em aware

            app.logger.debug(f"--- Fim verificação para {start_op_time} - {end_op_time} ---")

        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"\nTotal horários disponíveis únicos: {len(unique_available_slots)}")
        app.logger.info(f"===> Slots finais retornados: {unique_available_slots} <===")

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
    debug_mode = True # Forçar DEBUG
    app.logger.info(f"Iniciando servidor Flask porta {port} com debug={debug_mode}")
    app.run(host='0.0.0.0', port=port, debug=debug_mode)

# --- END OF FILE app.py ---

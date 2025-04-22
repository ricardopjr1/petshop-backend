import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date
from flask_cors import CORS
from typing import List, Tuple, Dict, Any, Set
import logging

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")

supabase: Client = create_client(url, key)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO)
app.logger.setLevel(logging.INFO)

CORS(app)

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
    """Determina a função necessária para realizar um serviço com base no nome."""
    if not service_name: return None
    service_name_lower = service_name.lower()
    # Prioritize Groomer if 'tosa' is mentioned
    if 'tosa' in service_name_lower:
        return 'Groomer'
    # Otherwise, check for Bath related terms
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower:
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função para o serviço '{service_name}'. Assumindo 'Banhista' por padrão.")
    # Default if no specific keyword is found
    return 'Banhista' # Defaulting to Banhista

def determine_dominant_role(roles: Set[str]) -> str | None:
    """Determina a função 'dominante' de um conjunto de funções (Groomer > Banhista)."""
    if not roles:
        return None
    if 'Groomer' in roles:
        return 'Groomer'
    if 'Banhista' in roles:
        return 'Banhista'
    # If only other roles or unrecognized roles are present, return the first one found
    # or handle as an error depending on requirements. Returning None might be safer.
    app.logger.warning(f"Nenhuma função dominante (Groomer/Banhista) encontrada no conjunto: {roles}. Verifique a configuração dos serviços.")
    # Fallback to Banhista if only non-standard roles were found, or return None?
    # Let's return None to indicate a potential configuration issue or unsupported mix.
    # If Banhista is always acceptable as a minimum, return 'Banhista'. Choose based on business logic.
    # Returning None for now to be stricter.
    return None


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """Busca e retorna os horários disponíveis para um ou mais nomes de serviços em uma data específica."""
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        data_str = request.args.get('data')
        # Use getlist to capture multiple values for the same key 'servicoNome'
        servico_nomes = request.args.getlist('servicoNome') # <<< CHANGED: Get service names
        empresa_id = request.args.get('empresaId')

        # Ensure names are strings and handle potential None values if getlist returns them
        servico_nomes = [str(nome) for nome in servico_nomes if nome]

        if not data_str or not servico_nomes or not empresa_id:
            app.logger.error("Erro: Parâmetros ausentes na requisição.")
            return jsonify({"message": "Parâmetros 'data', 'empresaId' e pelo menos um 'servicoNome' são obrigatórios."}), 400

        app.logger.info(f"Parâmetros recebidos: Data='{data_str}', Empresa='{empresa_id}', Serviços (nomes)='{servico_nomes}'") # <<< CHANGED Log message

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviços (nomes): {servico_nomes}") # <<< CHANGED Log message

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            app.logger.error(f"Erro crítico: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500

        # --- Get Operating Hours ---
        response_hours = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio')\
            .execute()

        if not response_hours.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404

        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response_hours.data:
            hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
            hora_fim_obj = parse_time(interval_data.get('hora_fim'))

            if hora_inicio_obj and hora_fim_obj and hora_fim_obj > hora_inicio_obj:
                operating_intervals.append((hora_inicio_obj, hora_fim_obj))
                app.logger.info(f"Intervalo de funcionamento válido encontrado: {hora_inicio_obj} - {hora_fim_obj}")
            else:
                app.logger.warning(f"Intervalo de funcionamento inválido ou mal formatado ignorado: {interval_data}. Verifique se hora_fim > hora_inicio.")

        if not operating_intervals:
             app.logger.error(f"Nenhum intervalo de funcionamento VÁLIDO encontrado para {dia_semana_nome} na empresa {empresa_id} após processamento.")
             return jsonify({"message": f"Erro ao processar horários de funcionamento para {dia_semana_nome}."}), 500

        # --- Get Details for ALL Selected Service Names ---
        # <<< CHANGED: Fetch by name ('nome') instead of 'id'
        response_services = supabase.table('servicos')\
            .select('nome, tempo_servico') \
            .eq('empresa_id', empresa_id)\
            .in_('nome', servico_nomes)\
            .execute()

        if not response_services.data:
            app.logger.warning(f"Nenhum dos serviços com nomes {servico_nomes} foi encontrado para a empresa {empresa_id}.")
            return jsonify({"message": "Nenhum dos serviços selecionados foi encontrado ou cadastrado corretamente."}), 404

        # Check if all requested service names were found
        found_service_names = {s['nome'] for s in response_services.data}
        requested_service_names_set = set(servico_nomes)
        if found_service_names != requested_service_names_set:
            missing_names = requested_service_names_set - found_service_names
            app.logger.warning(f"Alguns serviços solicitados não foram encontrados para esta empresa: {missing_names}")
            # Decide: error out or proceed with found services? Proceeding for now.
            # return jsonify({"message": f"Serviços não encontrados: {', '.join(missing_names)}"}), 404

        # --- Calculate Total Duration and Determine Required Role ---
        total_service_duration_minutes = 0
        actual_service_names_found: List[str] = [] # Use the names confirmed found in DB
        required_roles_set: Set[str] = set()

        for service_details in response_services.data: # Iterate only over services found in DB
            try:
                duration = int(service_details['tempo_servico'])
                if duration <= 0:
                    raise ValueError("Duração do serviço deve ser positiva.")
                total_service_duration_minutes += duration
                service_name = service_details['nome'] # Use the name from DB
                actual_service_names_found.append(service_name)
                role = get_required_role_for_service(service_name)
                if role:
                    required_roles_set.add(role)
                else:
                    # This case might be less likely if get_required_role_for_service has a default
                    app.logger.error(f"Não foi possível determinar a função para o serviço '{service_name}'.")
                    return jsonify({"message": f"Não foi possível determinar o tipo de profissional necessário para '{service_name}'."}), 500

            except (ValueError, TypeError, KeyError) as e:
                 app.logger.error(f"Valor inválido ou ausente para 'tempo_servico' no serviço '{service_details.get('nome', 'Desconhecido')}': {e}")
                 return jsonify({"message": f"Duração inválida ou não encontrada para o serviço '{service_details.get('nome', 'Desconhecido')}'."}), 500

        if total_service_duration_minutes == 0:
             # This could happen if only missing services were requested or all found services had 0 duration
             app.logger.error(f"Duração total calculada é zero para os serviços encontrados: {actual_service_names_found}.")
             return jsonify({"message": "Erro ao calcular a duração total dos serviços válidos."}), 500

        # Determine the single role needed based on the set of roles required by individual services found
        required_role = determine_dominant_role(required_roles_set)
        if not required_role:
             app.logger.error(f"Não foi possível determinar uma função única/válida para a combinação de serviços: {actual_service_names_found} (Funções necessárias: {required_roles_set})")
             return jsonify({"message": f"Não é possível combinar os serviços selecionados ou falta definição de profissional."}), 400

        app.logger.info(f"Serviços Considerados (encontrados): {actual_service_names_found}")
        app.logger.info(f"Duração Total Calculada: {total_service_duration_minutes} min")
        app.logger.info(f"Função Requerida Determinada: '{required_role}'")


        # --- Check Available Staff for the Determined Role ---
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Total de profissionais '{required_role}' disponíveis na empresa: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{required_role}' encontrado para a empresa {empresa_id} para realizar {actual_service_names_found}.")
            return jsonify({"message": f"Não há profissionais '{required_role}' disponíveis para realizar os serviços selecionados neste dia."}), 404

        # --- Get Existing Appointments for the Day ---
        # Assume 'servico' column in 'agendamentos' stores the service NAME
        response_appts = supabase.table('agendamentos')\
            .select('id, hora, servico') # 'servico' should be the service name
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()

        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Total de agendamentos encontrados na data {data_str}: {len(existing_appointments)}")

        # --- Calculate Busy Intervals for the Required Role ---
        busy_intervals: List[Dict[str, datetime]] = []
        processed_appts_count = 0
        relevant_appts_count = 0

        # Cache service details for appointments to avoid repeated DB calls inside the loop
        appt_service_details_cache = {}

        for appt in existing_appointments:
            processed_appts_count += 1
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico') # Name of the service in the existing appointment

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento ID {appt_id} com dados incompletos (hora ou nome do serviço). Ignorando.")
                continue

            # Fetch appointment's service details (use cache if available)
            # <<< This part still correctly uses the name from the appointment
            if appt_service_name not in appt_service_details_cache:
                resp_appt_svc = supabase.table('servicos')\
                    .select('tempo_servico, nome')\
                    .eq('empresa_id', empresa_id)\
                    .eq('nome', appt_service_name)\
                    .maybe_single()\
                    .execute()

                if not resp_appt_svc.data:
                    app.logger.warning(f"Não foram encontrados detalhes para o serviço '{appt_service_name}' do agendamento {appt_id}. Ignorando este agendamento para cálculo de ocupação.")
                    appt_service_details_cache[appt_service_name] = None # Cache the failure
                    continue
                else:
                     appt_service_details_cache[appt_service_name] = resp_appt_svc.data

            appt_svc_details = appt_service_details_cache[appt_service_name]
            if appt_svc_details is None: # Skip if fetching failed previously
                continue

            # Determine the role required for the *existing appointment's* service
            appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))

            # Only consider this appointment if it requires the *same type of professional*
            # as the *new booking* we are trying to make.
            if appt_required_role == required_role:
                relevant_appts_count += 1
                try:
                    appt_duration = int(appt_svc_details['tempo_servico'])
                    if appt_duration <= 0: raise ValueError("Duração inválida")
                    appt_start_time_obj = parse_time(appt_time_str)

                    if appt_start_time_obj:
                        appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                        if not appt_start_dt: raise ValueError("Falha ao combinar data/hora")

                        appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                        busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                        # app.logger.debug(f"Intervalo Ocupado por '{required_role}' adicionado: {appt_start_dt.time()} - {appt_end_dt.time()} (Appt ID: {appt_id})")
                    else:
                         app.logger.warning(f"Não foi possível converter a hora '{appt_time_str}' do agendamento {appt_id}. Ignorando.")

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' ou hora '{appt_time_str}' para agendamento {appt_id}: {e}. Ignorando.")

        app.logger.info(f"Total de agendamentos processados: {processed_appts_count}. Agendamentos relevantes para '{required_role}': {relevant_appts_count}. Intervalos ocupados por '{required_role}': {len(busy_intervals)}")

        # --- Generate Available Slots ---
        available_slots: List[str] = []
        interval_minutes = 15 # Check availability every 15 minutes

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)

            if not interval_start_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora para o intervalo {start_op_time}-{end_op_time}. Pulando intervalo.")
                continue

            # Calculate the latest possible start time for the *combined* service duration
            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            current_potential_dt = interval_start_dt

            app.logger.info(f"Verificando slots no intervalo {interval_start_dt.time()} - {interval_end_dt.time()} (duração total: {total_service_duration_minutes} min, último início: {last_possible_start_dt.time()})") # <<< CHANGED Log message

            while current_potential_dt <= last_possible_start_dt:
                # Calculate the end time for this potential slot using the *total* duration
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                # Ensure the potential slot fits within the current operating interval
                if potential_end_dt > interval_end_dt:
                     current_potential_dt += timedelta(minutes=interval_minutes)
                     continue

                # Check how many existing appointments (requiring the same role) overlap with this potential slot
                overlapping_count = 0
                for busy in busy_intervals:
                    # Check for overlap: (SlotStart < BusyEnd) and (SlotEnd > BusyStart)
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1

                # If the number of overlapping appointments is less than the number of available staff for that role, the slot is available
                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))

                # Move to the next potential start time
                current_potential_dt += timedelta(minutes=interval_minutes)

        # Remove duplicates and sort
        unique_available_slots = sorted(list(set(available_slots)))

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{required_role}' (duração {total_service_duration_minutes} min) em {selected_date}: {len(unique_available_slots)}")

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    # Set debug=False for production
    app.run(host='0.0.0.0', port=5000, debug=True)

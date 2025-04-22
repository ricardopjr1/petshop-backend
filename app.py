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

ROLE_HIERARCHY = {
    'Banhista': 1,
    'Groomer': 2,
}
DEFAULT_ROLE_LEVEL = 0

def parse_time(time_str: str) -> time | None:
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
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)

def get_required_role_for_service(service_name: str) -> str | None:
    if not service_name: return None
    service_name_lower = service_name.lower()
    if 'tosa' in service_name_lower:
        return 'Groomer'
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower:
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'

def get_highest_required_role(roles: Set[str]) -> str | None:
    if not roles:
        return None

    highest_role = None
    max_level = -1

    for role in roles:
        level = ROLE_HIERARCHY.get(role, DEFAULT_ROLE_LEVEL)
        if level > max_level:
            max_level = level
            highest_role = role
        elif highest_role is None:
            highest_role = role

    if highest_role is None and roles:
         first_role = next(iter(roles))
         app.logger.warning(f"Nenhuma das funções {roles} está na hierarquia definida. Usando a primeira: {first_role}")
         return first_role

    return highest_role


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        data_str = request.args.get('data')
        servico_ids_str_list = request.args.getlist('servicoIds')
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_ids_str_list or not empresa_id:
            app.logger.error("Erro: Parâmetros ausentes na requisição.")
            return jsonify({"message": "Parâmetros 'data', 'servicoIds' (um ou mais) e 'empresaId' são obrigatórios."}), 400

        try:
            servico_ids = [int(sid) for sid in servico_ids_str_list]
            if not servico_ids:
                 raise ValueError("Lista de servicoIds não pode ser vazia.")
        except ValueError:
            app.logger.error(f"Erro: 'servicoIds' contém valores inválidos: {servico_ids_str_list}.")
            return jsonify({"message": "'servicoIds' deve conter apenas IDs numéricos válidos."}), 400

        app.logger.info(f"IDs de Serviço recebidos: {servico_ids}")

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviços: {servico_ids}")

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            app.logger.error(f"Erro crítico: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500

        response = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio')\
            .execute()

        if not response.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404

        operating_intervals: List[Tuple[time, time]] = []
        for interval_data in response.data:
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

        response_servicos = supabase.table('servicos')\
            .select('id, tempo_servico, nome')\
            .eq('empresa_id', empresa_id)\
            .in_('id', servico_ids)\
            .execute()

        if not response_servicos.data:
            app.logger.warning(f"Nenhum dos serviços com IDs {servico_ids} foi encontrado para a empresa {empresa_id}.")
            return jsonify({"message": "Um ou mais serviços selecionados não foram encontrados."}), 404

        found_ids = {s['id'] for s in response_servicos.data}
        requested_ids = set(servico_ids)
        if found_ids != requested_ids:
             missing_ids = requested_ids - found_ids
             app.logger.warning(f"Serviços solicitados não encontrados: IDs {missing_ids}")


        total_service_duration_minutes = 0
        required_roles_set: Set[str] = set()
        service_names: List[str] = []

        for service_details in response_servicos.data:
            try:
                duration = int(service_details['tempo_servico'])
                if duration <= 0:
                    raise ValueError(f"Duração inválida ({duration}) para serviço ID {service_details['id']}")
                total_service_duration_minutes += duration
                service_name = service_details.get('nome', f"Serviço ID {service_details['id']}")
                service_names.append(service_name)
                role = get_required_role_for_service(service_name)
                if role:
                    required_roles_set.add(role)

            except (ValueError, TypeError, KeyError) as e:
                 app.logger.error(f"Erro ao processar detalhe do serviço ID {service_details.get('id')}: {e}")
                 return jsonify({"message": f"Erro nos dados do serviço {service_details.get('nome', service_details.get('id'))}. Verifique a configuração."}), 500

        if total_service_duration_minutes <= 0:
             app.logger.error("Duração total calculada é zero ou negativa.")
             return jsonify({"message": "Erro ao calcular a duração total dos serviços."}), 500

        highest_required_role = get_highest_required_role(required_roles_set)

        if not highest_required_role:
             app.logger.error(f"Não foi possível determinar a função necessária para os serviços selecionados: {service_names}")
             return jsonify({"message": "Não foi possível determinar o tipo de profissional necessário para os serviços selecionados."}), 500

        app.logger.info(f"Serviços: {', '.join(service_names)}. Duração Total={total_service_duration_minutes} min, Requer Função Mais Alta='{highest_required_role}'")

        response = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', highest_required_role)\
            .execute()

        available_staff_count = response.count if response.count is not None else 0
        app.logger.info(f"Total de profissionais '{highest_required_role}' disponíveis na empresa: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{highest_required_role}' encontrado para a empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais disponíveis ({highest_required_role}) para realizar a combinação de serviços selecionada."}), 404

        response = supabase.table('agendamentos')\
            .select('id, hora, servico')\
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()

        existing_appointments = response.data if response.data else []
        app.logger.info(f"Total de agendamentos encontrados na data {data_str}: {len(existing_appointments)}")

        busy_intervals: List[Dict[str, datetime]] = []
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

            resp_appt_svc = supabase.table('servicos')\
                .select('tempo_servico, nome')\
                .eq('empresa_id', empresa_id)\
                .eq('nome', appt_service_name)\
                .maybe_single()\
                .execute()

            if not resp_appt_svc.data:
                app.logger.warning(f"Não foram encontrados detalhes para o serviço '{appt_service_name}' do agendamento {appt_id}. Ignorando este agendamento para cálculo de ocupação.")
                continue

            appt_svc_details = resp_appt_svc.data
            appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))

            if appt_required_role == highest_required_role:
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
                    else:
                         app.logger.warning(f"Não foi possível converter a hora '{appt_time_str}' do agendamento {appt_id}. Ignorando.")

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' ou hora '{appt_time_str}' para agendamento {appt_id}: {e}. Ignorando.")

        app.logger.info(f"Total de agendamentos processados: {processed_appts_count}. Agendamentos relevantes para '{highest_required_role}': {relevant_appts_count}. Intervalos ocupados: {len(busy_intervals)}")

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

            app.logger.info(f"Verificando slots no intervalo {interval_start_dt.time()} - {interval_end_dt.time()} (último início possível: {last_possible_start_dt.time()} para {total_service_duration_minutes} min)")

            while current_potential_dt <= last_possible_start_dt:
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                if potential_end_dt > interval_end_dt:
                     current_potential_dt += timedelta(minutes=interval_minutes)
                     continue

                overlapping_count = 0
                for busy in busy_intervals:
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1

                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))

                current_potential_dt += timedelta(minutes=interval_minutes)

        unique_available_slots = sorted(list(set(available_slots)))

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{highest_required_role}' (duração {total_service_duration_minutes} min) em {selected_date}: {len(unique_available_slots)}")

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date
from flask_cors import CORS

load_dotenv()

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")

supabase: Client = create_client(url, key)

app = Flask(__name__)
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
    elif 'banho' in service_name_lower:
         return 'Banhista'
    elif 'hidratação' in service_name_lower:
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        data_str = request.args.get('data')
        servico_id = request.args.get('servicoId')
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_id or not empresa_id:
            app.logger.error("Erro: Parâmetros ausentes na requisição.")
            return jsonify({"message": "Parâmetros 'data', 'servicoId' e 'empresaId' são obrigatórios."}), 400

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviço: {servico_id}")

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            app.logger.warning(f"Dia da semana {dia_semana_num} não mapeado em DIAS_SEMANA_PT.")
            return jsonify({"message": "Dia da semana não configurado para funcionamento."}), 404

        response = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .execute()

        if not response.data:
            app.logger.info(f"Nenhum horário de funcionamento encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404

        operating_hours = response.data[0]
        hora_inicio_op_obj = parse_time(operating_hours.get('hora_inicio'))
        hora_fim_op_obj = parse_time(operating_hours.get('hora_fim'))

        if not hora_inicio_op_obj or not hora_fim_op_obj:
             app.logger.error("Erro ao converter hora_inicio ou hora_fim do banco de dados.")
             return jsonify({"message": "Erro interno ao processar horário de funcionamento."}), 500

        app.logger.info(f"Horário de funcionamento: {hora_inicio_op_obj} - {hora_fim_op_obj}")

        response = supabase.table('servicos')\
            .select('tempo_servico, nome')\
            .eq('id', servico_id)\
            .eq('empresa_id', empresa_id)\
            .maybe_single()\
            .execute()

        if not response.data:
            app.logger.warning(f"Serviço com ID {servico_id} não encontrado para a empresa {empresa_id}.")
            return jsonify({"message": "Serviço não encontrado."}), 404

        service_details = response.data
        try:
            service_duration_minutes = int(service_details['tempo_servico'])
        except (ValueError, TypeError, KeyError):
             app.logger.error(f"Valor inválido ou ausente para 'tempo_servico' no serviço {servico_id}.")
             return jsonify({"message": "Duração do serviço inválida ou não encontrada no banco de dados."}), 500
        if service_duration_minutes <= 0:
            app.logger.error(f"Duração do serviço inválida (zero ou negativa): {service_duration_minutes}")
            return jsonify({"message": "Duração do serviço configurada incorretamente."}), 500


        service_name = service_details.get('nome', 'Nome Desconhecido')
        required_role = get_required_role_for_service(service_name)

        if not required_role:
             app.logger.error(f"Não foi possível determinar a função necessária para o serviço '{service_name}' (ID: {servico_id}).")
             return jsonify({"message": f"Não foi possível determinar o tipo de profissional necessário para '{service_name}'."}), 500

        app.logger.info(f"Detalhes do serviço '{service_name}': Duração={service_duration_minutes} min, Requer={required_role}")

        response = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response.count if response.count is not None else 0
        app.logger.info(f"Profissionais disponíveis com função '{required_role}': {available_staff_count}")

        if available_staff_count == 0:
            return jsonify({"message": f"Nenhum profissional ({required_role}) disponível para realizar este serviço."}), 404

        response = supabase.table('agendamentos')\
            .select('id, hora, servico')\
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()

        existing_appointments = response.data if response.data else []
        app.logger.info(f"Total de agendamentos encontrados na data {data_str}: {len(existing_appointments)}")

        busy_intervals = []
        processed_appts_count = 0
        relevant_appts_count = 0

        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento existente {appt_id} sem hora ou nome de serviço. Ignorando.")
                continue

            resp_appt_svc = supabase.table('servicos')\
                .select('tempo_servico, nome')\
                .eq('empresa_id', empresa_id)\
                .eq('nome', appt_service_name)\
                .maybe_single()\
                .execute()

            processed_appts_count += 1
            if resp_appt_svc.data:
                appt_svc_details = resp_appt_svc.data
                appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))

                if appt_required_role == required_role:
                    relevant_appts_count += 1
                    try:
                        appt_duration = int(appt_svc_details['tempo_servico'])
                        appt_start_time_obj = parse_time(appt_time_str)

                        if appt_start_time_obj:
                            appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                            appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                            busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})

                    except (ValueError, TypeError, KeyError) as e:
                        app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' para agendamento {appt_id}: {e}")
            else:
                 app.logger.warning(f"Não encontrou detalhes do serviço '{appt_service_name}' para o agendamento existente {appt_id}.")

        app.logger.info(f"Processados {processed_appts_count} agendamentos. {relevant_appts_count} relevantes para '{required_role}'.")

        available_slots = []
        interval_minutes = 15

        current_potential_dt = combine_date_time(selected_date, hora_inicio_op_obj)
        operation_end_dt = combine_date_time(selected_date, hora_fim_op_obj)

        if not current_potential_dt or not operation_end_dt:
            app.logger.error("Erro fatal ao combinar data/hora de operação.")
            return jsonify({"message": "Erro interno ao calcular horários de operação."}), 500

        last_possible_start_dt = operation_end_dt - timedelta(minutes=service_duration_minutes)

        app.logger.info(f"Verificando slots a cada {interval_minutes} min, de {current_potential_dt.time()} até {last_possible_start_dt.time()} (último início).")

        while current_potential_dt <= last_possible_start_dt:
            potential_end_dt = current_potential_dt + timedelta(minutes=service_duration_minutes)

            if potential_end_dt.time() > hora_fim_op_obj and hora_fim_op_obj != time(0, 0):
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

        app.logger.info(f"Horários disponíveis calculados para '{required_role}': {unique_available_slots}")
        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

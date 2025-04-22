import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date
from flask_cors import CORS
from typing import List, Tuple, Dict, Any
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
    if 'tosa' in service_name_lower:
        return 'Groomer'
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower:
         return 'Banhista'
    app.logger.warning(f"Não foi possível determinar a função para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """Busca e retorna os horários disponíveis para um serviço em uma data específica."""
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
            if service_duration_minutes <= 0:
                raise ValueError("Duração do serviço deve ser positiva.")
        except (ValueError, TypeError, KeyError):
             app.logger.error(f"Valor inválido, zero, negativo ou ausente para 'tempo_servico' no serviço {servico_id}.")
             return jsonify({"message": "Duração do serviço inválida ou não encontrada."}), 500

        service_name = service_details.get('nome', 'Nome Desconhecido')
        required_role = get_required_role_for_service(service_name)

        if not required_role:
             app.logger.error(f"Não foi possível determinar a função necessária para o serviço '{service_name}' (ID: {servico_id}).")
             return jsonify({"message": f"Não foi possível determinar o tipo de profissional necessário para '{service_name}'."}), 500

        app.logger.info(f"Detalhes do serviço '{service_name}': Duração={service_duration_minutes} min, Requer Função='{required_role}'")

        response = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response.count if response.count is not None else 0
        app.logger.info(f"Total de profissionais '{required_role}' disponíveis na empresa: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{required_role}' encontrado para a empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais disponíveis para realizar este serviço ({service_name}) neste dia."}), 404

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
                    else:
                         app.logger.warning(f"Não foi possível converter a hora '{appt_time_str}' do agendamento {appt_id}. Ignorando.")

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' ou hora '{appt_time_str}' para agendamento {appt_id}: {e}. Ignorando.")

        app.logger.info(f"Total de agendamentos processados: {processed_appts_count}. Agendamentos relevantes para '{required_role}': {relevant_appts_count}. Intervalos ocupados: {len(busy_intervals)}")

        available_slots: List[str] = []
        interval_minutes = 15

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)

            if not interval_start_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora para o intervalo {start_op_time}-{end_op_time}. Pulando intervalo.")
                continue

            last_possible_start_dt = interval_end_dt - timedelta(minutes=service_duration_minutes)
            current_potential_dt = interval_start_dt

            app.logger.info(f"Verificando slots no intervalo {interval_start_dt.time()} - {interval_end_dt.time()} (último início possível: {last_possible_start_dt.time()})")

            while current_potential_dt <= last_possible_start_dt:
                potential_end_dt = current_potential_dt + timedelta(minutes=service_duration_minutes)

                if potential_end_dt > interval_end_dt:
                     app.logger.warning(f"Slot potencial {current_potential_dt.time()} ({service_duration_minutes} min) terminaria após o fim do intervalo ({interval_end_dt.time()}). Ignorando.")
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

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{required_role}' em {selected_date}: {len(unique_available_slots)}")

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

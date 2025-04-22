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

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")

supabase: Client = create_client(url, key)

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s') # Added format
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
        # Try HH:MM:SS first, as it's more specific
        return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try:
            # Fallback to HH:MM
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
    # Consider common bath-related terms
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower or 'pelo' in service_name_lower:
         return 'Banhista'
    # Fallback for unknown services - adjust as needed
    app.logger.warning(f"Não foi possível determinar a função específica para o serviço '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista'

def get_required_role_for_multiple_services(service_names: List[str]) -> str:
    """Determina a função MAIS EXIGENTE necessária para uma lista de serviços."""
    if not service_names:
        app.logger.warning("Lista de nomes de serviço vazia ao determinar função. Assumindo 'Banhista'.")
        return 'Banhista' # Default role

    contains_tosa = any('tosa' in name.lower() for name in service_names)
    if contains_tosa:
        app.logger.info("Pelo menos um serviço de 'tosa' detectado. Função requerida: Groomer.")
        return 'Groomer'
    else:
        app.logger.info("Nenhum serviço de 'tosa' detectado. Função requerida: Banhista.")
        return 'Banhista'


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    """
    Busca e retorna os horários disponíveis para UM ou MÚLTIPLOS serviços
    em uma data específica. Para múltiplos, calcula a duração total e usa
    a função mais exigente (Groomer > Banhista).
    """
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        data_str = request.args.get('data')
        # --- MODIFICADO: Receber múltiplos IDs ---
        servico_ids_str = request.args.get('servicoIds') # Alterado de 'servicoId'
        empresa_id = request.args.get('empresaId')

        # --- MODIFICADO: Validação dos IDs ---
        if not data_str or not servico_ids_str or not empresa_id:
            app.logger.error("Erro: Parâmetros ausentes. 'data', 'servicoIds' e 'empresaId' são obrigatórios.")
            # Alterado nome do parâmetro na mensagem
            return jsonify({"message": "Parâmetros 'data', 'servicoIds' e 'empresaId' são obrigatórios."}), 400

        try:
            # Validar e converter IDs
            servico_ids = [int(sid.strip()) for sid in servico_ids_str.split(',') if sid.strip()]
            if not servico_ids:
                raise ValueError("Lista de IDs de serviço está vazia ou contém valores inválidos.")
        except ValueError as e:
            app.logger.error(f"Erro: IDs de serviço inválidos '{servico_ids_str}'. {e}")
            return jsonify({"message": "Formato de IDs de serviço inválido. Use uma lista de números separados por vírgula (ex: 1,2,3)."}), 400
        # --- Fim da Modificação ---

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviços IDs: {servico_ids}")

        # ... (Lógica de buscar horário de funcionamento permanece a mesma) ...
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            app.logger.error(f"Erro crítico: Dia da semana {dia_semana_num} não mapeado.")
            return jsonify({"message": "Erro interno ao determinar o dia da semana."}), 500

        # Fetch operating hours
        response_op_hours = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio')\
            .execute()

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
                 app.logger.warning(f"Intervalo de funcionamento inválido ou mal formatado ignorado: {interval_data}. Verifique se hora_fim > hora_inicio.")

        if not operating_intervals:
              app.logger.error(f"Nenhum intervalo de funcionamento VÁLIDO encontrado para {dia_semana_nome} na empresa {empresa_id} após processamento.")
              return jsonify({"message": f"Erro ao processar horários de funcionamento para {dia_semana_nome}."}), 500

        # --- MODIFICADO: Buscar detalhes de MÚLTIPLOS serviços ---
        response_services = supabase.table('servicos')\
            .select('id, tempo_servico, nome') # Incluído 'id' para melhor log de erro
            .in_('id', servico_ids) # Usar .in_ para buscar múltiplos IDs
            .eq('empresa_id', empresa_id)\
            .execute()

        if not response_services.data or len(response_services.data) != len(servico_ids):
            found_ids = [s['id'] for s in response_services.data] if response_services.data else []
            missing_ids = list(set(servico_ids) - set(found_ids))
            app.logger.warning(f"Um ou mais serviços com IDs {servico_ids} não foram encontrados para a empresa {empresa_id}. IDs não encontrados: {missing_ids}")
            return jsonify({"message": f"Um ou mais serviços selecionados não foram encontrados (IDs: {missing_ids})."}), 404

        # Calcular duração total e determinar a função requerida (Opção A)
        total_service_duration_minutes = 0
        service_names: List[str] = []
        service_details_list = response_services.data

        for service_detail in service_details_list:
            try:
                duration = int(service_detail['tempo_servico'])
                if duration <= 0:
                    raise ValueError("Duração do serviço deve ser positiva.")
                total_service_duration_minutes += duration
                service_names.append(service_detail.get('nome', 'Nome Desconhecido'))
            except (ValueError, TypeError, KeyError) as e:
                 service_id_error = service_detail.get('id', 'N/A')
                 app.logger.error(f"Valor inválido, zero, negativo ou ausente para 'tempo_servico' no serviço ID {service_id_error}. Erro: {e}")
                 return jsonify({"message": f"Duração inválida encontrada para o serviço ID {service_id_error}."}), 500

        # Determina a função MAIS EXIGENTE baseada nos nomes dos serviços
        required_role = get_required_role_for_multiple_services(service_names)

        app.logger.info(f"Detalhes dos serviços solicitados: IDs={servico_ids}, Nomes={service_names}")
        app.logger.info(f"Duração TOTAL calculada: {total_service_duration_minutes} min. Função requerida para o bloco: '{required_role}'")
        # --- Fim da Modificação ---

        # Buscar contagem de staff para a função requerida (lógica existente funciona)
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .execute()

        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Total de profissionais '{required_role}' disponíveis na empresa: {available_staff_count}")

        if available_staff_count == 0:
            app.logger.warning(f"Nenhum profissional '{required_role}' encontrado para a empresa {empresa_id}.")
            return jsonify({"message": f"Não há profissionais disponíveis ({required_role}) para realizar a combinação de serviços selecionada."}), 404 # Mensagem mais clara

        # Buscar agendamentos existentes (lógica existente funciona)
        response_appts = supabase.table('agendamentos')\
            .select('id, hora, servico')\
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .execute()

        existing_appointments = response_appts.data if response_appts.data else []
        app.logger.info(f"Total de agendamentos encontrados na data {data_str}: {len(existing_appointments)}")

        # --- MODIFICADO: Calcular intervalos ocupados relevantes para a FUNÇÃO REQUERIDA ---
        role_specific_busy_intervals: List[Dict[str, datetime]] = []
        processed_appts_count = 0
        relevant_appts_count = 0

        # Cache para detalhes de serviços de agendamentos existentes (evita queries repetidas)
        appt_service_details_cache: Dict[str, Dict[str, Any]] = {}

        for appt in existing_appointments:
            processed_appts_count += 1
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico') # Assume que 'servico' na tabela agendamentos é o NOME

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento ID {appt_id} com dados incompletos (hora ou nome do serviço). Ignorando.")
                continue

            appt_svc_details = appt_service_details_cache.get(appt_service_name)
            if not appt_svc_details:
                # Buscar detalhes do serviço do agendamento existente se não estiver no cache
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
                appt_service_details_cache[appt_service_name] = appt_svc_details # Adiciona ao cache

            # Determina a função para o serviço DESTE agendamento
            appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))

            # SÓ considera este agendamento como 'ocupado' se a sua função
            # for a MESMA que a função requerida para o NOVO agendamento múltiplo
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
                        # Adiciona aos intervalos ocupados ESPECÍFICOS DA FUNÇÃO
                        role_specific_busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                        app.logger.debug(f"Agendamento {appt_id} ({appt_service_name}) adicionado aos ocupados para {required_role}: {appt_start_dt.time()} - {appt_end_dt.time()}")

                    else:
                         app.logger.warning(f"Não foi possível converter a hora '{appt_time_str}' do agendamento {appt_id}. Ignorando.")

                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao processar detalhes do serviço '{appt_service_name}' ou hora '{appt_time_str}' para agendamento {appt_id}: {e}. Ignorando.")
            # else:
                # app.logger.debug(f"Agendamento {appt_id} ({appt_service_name}, req: {appt_required_role}) ignorado pois a função requerida é {required_role}.")


        app.logger.info(f"Total de agendamentos processados: {processed_appts_count}. Agendamentos relevantes para '{required_role}': {relevant_appts_count}.")
        app.logger.info(f"Intervalos ocupados rastreados para '{required_role}': {len(role_specific_busy_intervals)}")
        # --- Fim da Modificação ---


        # --- MODIFICADO: Calcular slots usando a DURAÇÃO TOTAL e intervalos da FUNÇÃO ---
        available_slots: List[str] = []
        interval_minutes = 15 # Intervalo entre possíveis horários de início

        for start_op_time, end_op_time in operating_intervals:
            interval_start_dt = combine_date_time(selected_date, start_op_time)
            interval_end_dt = combine_date_time(selected_date, end_op_time)

            if not interval_start_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora para o intervalo {start_op_time}-{end_op_time}. Pulando intervalo.")
                continue

            # O último horário possível para INICIAR o bloco de serviços
            last_possible_start_dt = interval_end_dt - timedelta(minutes=total_service_duration_minutes)
            current_potential_dt = interval_start_dt

            app.logger.info(f"Verificando slots no intervalo {interval_start_dt.time()} - {interval_end_dt.time()} (duração: {total_service_duration_minutes} min, último início possível: {last_possible_start_dt.time()})")

            while current_potential_dt <= last_possible_start_dt:
                # Calcula o fim do bloco de serviços
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                # Verifica se o bloco TERMINA dentro do horário de funcionamento atual
                # (Já garantimos que começa antes do last_possible_start_dt)
                if potential_end_dt > interval_end_dt:
                     # Este log não deveria mais ser necessário devido à condição do while, mas deixamos por segurança
                     app.logger.debug(f"Slot potencial {current_potential_dt.time()} ({total_service_duration_minutes} min) terminaria após o fim do intervalo ({interval_end_dt.time()}). Ignorando.")
                     # Incrementa e continua o loop
                     current_potential_dt += timedelta(minutes=interval_minutes)
                     continue

                # Conta quantos agendamentos existentes (DA FUNÇÃO REQUERIDA)
                # se sobrepõem com este slot potencial
                overlapping_count = 0
                for busy in role_specific_busy_intervals: # Usa os intervalos da função!
                    # Verifica sobreposição: (StartA < EndB) and (EndA > StartB)
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1
                        app.logger.debug(f"Slot potencial {current_potential_dt.strftime('%H:%M')}-{potential_end_dt.strftime('%H:%M')} sobrepõe com agendamento {busy['start'].strftime('%H:%M')}-{busy['end'].strftime('%H:%M')}. Contagem atual: {overlapping_count}")


                # Se o número de sobreposições for MENOR que o número total
                # de funcionários disponíveis PARA AQUELA FUNÇÃO, o slot está livre!
                if overlapping_count < available_staff_count:
                    slot_time_str = current_potential_dt.strftime('%H:%M')
                    available_slots.append(slot_time_str)
                    app.logger.debug(f"Slot {slot_time_str} DISPONÍVEL ({overlapping_count} ocupados < {available_staff_count} {required_role} disponíveis)")
                # else:
                    # app.logger.debug(f"Slot {current_potential_dt.strftime('%H:%M')} INDISPONÍVEL ({overlapping_count} ocupados >= {available_staff_count} {required_role} disponíveis)")


                # Avança para o próximo horário potencial
                current_potential_dt += timedelta(minutes=interval_minutes)
        # --- Fim da Modificação ---

        # Remover duplicados e ordenar (a lógica existente funciona)
        unique_available_slots = sorted(list(set(available_slots)))

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{required_role}' (duração {total_service_duration_minutes} min) em {selected_date}: {len(unique_available_slots)}")
        app.logger.info(f"Horários disponíveis: {unique_available_slots}")

        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    # Use 'debug=False' em produção
    app.run(host='0.0.0.0', port=os.getenv('PORT', 5000), debug=os.getenv('FLASK_DEBUG', 'false').lower() == 'true')

# --- END OF FILE app.py ---

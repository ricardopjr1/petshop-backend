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
CORS(app) # Habilita CORS para todas as origens

DIAS_SEMANA_PT = {
    0: 'Segunda-Feira', 1: 'Terça-Feira', 2: 'Quarta-Feira',
    3: 'Quinta-Feira', 4: 'Sexta-Feira', 5: 'Sábado', 6: 'Domingo'
}

# --- Funções Auxiliares ---

def parse_time(time_str: str) -> time | None:
    # ... (código mantido igual) ...
    if not time_str: return None
    try: return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try: return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            app.logger.error(f"Formato de hora inválido: {time_str}.")
            return None

def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    # ... (código mantido igual) ...
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)

def get_required_role_for_service(service_name: str) -> str | None:
    # AJUSTADO: Tenta identificar "Banho e Tosa" também
    # !!! PALIATIVO: Ideal é ter coluna 'funcao_necessaria' em 'servicos' !!!
    if not service_name: return None
    service_name_lower = service_name.lower()
    # Verifica primeiro a combinação mais específica
    if 'banho' in service_name_lower and 'tosa' in service_name_lower:
        return 'Banho e Tosa'
    elif 'tosa' in service_name_lower: # Se tem tosa, mas não banho junto (ou nome não especifica)
        return 'Groomer' # Assume Groomer (pode precisar ajustar)
    elif 'banho' in service_name_lower: # Se tem banho, mas não tosa
         return 'Banhista'
    elif 'hidratação' in service_name_lower: # Exemplo adicional
         return 'Banhista'
    # Se nenhuma palavra chave encontrada, retorna um padrão (ou None se preferir erro)
    # app.logger.warning(f"Função não determinada para '{service_name}'. Assumindo 'Banhista'.")
    return 'Banhista' # Padrão

def determine_overall_required_role(service_details_list: list) -> str | None:
    """
    Determina a função de maior prioridade necessária com base em uma lista de serviços.
    Prioridade: "Banho e Tosa" > "Groomer" > "Banhista".
    """
    required_roles = set()
    for service in service_details_list:
        role = get_required_role_for_service(service.get('nome'))
        if role:
            required_roles.add(role)

    if not required_roles:
        return None # Nenhum serviço válido ou função determinada

    if 'Banho e Tosa' in required_roles:
        return 'Banho e Tosa'
    elif 'Groomer' in required_roles:
        return 'Groomer'
    elif 'Banhista' in required_roles:
        return 'Banhista'
    else:
        return None # Caso inesperado

# --- Rota Principal da API ---

@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        # 1. Obter Parâmetros (MODIFICADO para aceitar múltiplos IDs)
        data_str = request.args.get('data')
        servico_ids_str = request.args.get('servicoIds') # Espera 'id1,id2,id3'
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_ids_str or not empresa_id:
            app.logger.error("Erro: Parâmetros 'data', 'servicoIds' e 'empresaId' são obrigatórios.")
            return jsonify({"message": "Parâmetros 'data', 'servicoIds' e 'empresaId' são obrigatórios."}), 400

        # Valida e converte IDs de serviço
        servico_ids_list = [sid.strip() for sid in servico_ids_str.split(',') if sid.strip()]
        if not servico_ids_list:
             app.logger.error("Erro: Lista de 'servicoIds' está vazia.")
             return jsonify({"message": "Pelo menos um ID de serviço deve ser fornecido em 'servicoIds'."}), 400

        # Valida data
        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400
        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             return jsonify({"message": "Não é possível agendar para datas passadas."}), 400

        app.logger.info(f"Buscando: Empresa={empresa_id}, Data={selected_date}, Serviços IDs={servico_ids_list}")

        # 2. Buscar Horário de Funcionamento (Lógica mantida)
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome: return jsonify({"message": "Dia da semana não configurado."}), 404
        response_hf = supabase.table('horarios_funcionamento').select('hora_inicio, hora_fim').eq('empresa_id', empresa_id).eq('dia_semana', dia_semana_nome).eq('ativo', True).execute()
        if not response_hf.data: return jsonify({"message": f"Petshop fechado em {dia_semana_nome}."}), 404
        operating_hours = response_hf.data[0]
        hora_inicio_op_obj = parse_time(operating_hours.get('hora_inicio'))
        hora_fim_op_obj = parse_time(operating_hours.get('hora_fim'))
        if not hora_inicio_op_obj or not hora_fim_op_obj: return jsonify({"message": "Erro horário funcionamento."}), 500
        app.logger.info(f"Funcionamento: {hora_inicio_op_obj} - {hora_fim_op_obj}")

        # 3. Buscar Detalhes de MÚLTIPLOS Serviços (MODIFICADO)
        response_sv = supabase.table('servicos')\
            .select('id, tempo_servico, nome')\
            .in_('id', servico_ids_list)\
            .eq('empresa_id', empresa_id)\
            .execute() # Não usa mais maybe_single()

        if response_sv.error:
             app.logger.error(f"Erro Supabase ao buscar serviços: {response_sv.error}")
             return jsonify({"message": "Erro ao buscar detalhes dos serviços."}), 500
        if not response_sv.data or len(response_sv.data) != len(servico_ids_list):
            # Verifica se todos os IDs solicitados foram encontrados
            found_ids = {str(s['id']) for s in response_sv.data}
            missing_ids = [sid for sid in servico_ids_list if sid not in found_ids]
            app.logger.warning(f"Um ou mais IDs de serviço não encontrados ou inválidos: {missing_ids}")
            return jsonify({"message": f"Um ou mais serviços selecionados são inválidos: {', '.join(missing_ids)}"}), 404

        service_details_list = response_sv.data

        # 4. Calcular DURAÇÃO TOTAL e Determinar FUNÇÃO GERAL (NOVO)
        total_service_duration_minutes = 0
        for service in service_details_list:
            try:
                duration = int(service['tempo_servico'])
                if duration < 0: # Não permitir duração negativa
                     app.logger.error(f"Duração negativa encontrada para serviço {service['id']}: {duration}")
                     return jsonify({"message": f"Serviço '{service.get('nome')}' possui duração inválida."}), 500
                total_service_duration_minutes += duration
            except (ValueError, TypeError, KeyError):
                app.logger.error(f"tempo_servico inválido/ausente para serviço {service['id']}.")
                return jsonify({"message": f"Duração inválida para o serviço '{service.get('nome')}'."}), 500

        # Verifica se a duração total não é zero (importante para o loop)
        if total_service_duration_minutes <= 0:
            app.logger.error(f"Duração total calculada é zero ou negativa: {total_service_duration_minutes}")
            return jsonify({"message": "A duração total dos serviços selecionados é inválida (zero ou negativa)."}), 400

        # Determina a função necessária com base em TODOS os serviços
        overall_required_role = determine_overall_required_role(service_details_list)
        if not overall_required_role:
            app.logger.error("Não foi possível determinar a função geral necessária para os serviços selecionados.")
            return jsonify({"message": "Não foi possível determinar o profissional necessário para os serviços."}), 500

        app.logger.info(f"Serviços selecionados: {len(service_details_list)}, Duração Total: {total_service_duration_minutes} min, Requer Função Geral: {overall_required_role}")

        # 5. Contar Profissionais Disponíveis (MODIFICADO para usar overall_required_role)
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', overall_required_role)\
            .execute()
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Staff disponível ({overall_required_role}): {available_staff_count}")
        if available_staff_count == 0:
            return jsonify({"message": f"Nenhum profissional ({overall_required_role}) disponível."}), 404

        # 6. Buscar Agendamentos Existentes (Lógica mantida)
        response_ag = supabase.table('agendamentos').select('id, hora, servico').eq('empresa_id', empresa_id).eq('data', data_str).execute()
        existing_appointments = response_ag.data if response_ag.data else []
        app.logger.info(f"Agendamentos existentes na data: {len(existing_appointments)}")

        # 7. Processar Agendamentos Existentes (MODIFICADO para comparar com overall_required_role)
        busy_intervals = []
        relevant_appts_count = 0
        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico')
            if not appt_time_str or not appt_service_name: continue

            # Ineficiente: Busca detalhes do serviço para CADA agendamento existente
            resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
            if resp_appt_svc.data:
                appt_svc_details = resp_appt_svc.data
                # Determina a função para ESTE agendamento
                appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))

                # SÓ CONSIDERA se a função deste agendamento é a MESMA função GERAL que estamos tentando agendar
                if appt_required_role == overall_required_role:
                    relevant_appts_count += 1
                    try:
                        appt_duration = int(appt_svc_details['tempo_servico'])
                        appt_start_time_obj = parse_time(appt_time_str)
                        if appt_start_time_obj:
                            appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                            appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                            busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                    except (ValueError, TypeError, KeyError) as e:
                        app.logger.warning(f"Erro processando agendamento existente {appt_id}: {e}")
            else:
                 app.logger.warning(f"Detalhes não encontrados para serviço '{appt_service_name}' agendamento {appt_id}.")
        app.logger.info(f"Agendamentos relevantes ({overall_required_role}): {relevant_appts_count}")

        # 8. Gerar e Verificar Slots Potenciais (MODIFICADO para usar duração TOTAL)
        available_slots = []
        interval_minutes = 15 # Ou outro valor desejado
        current_potential_dt = combine_date_time(selected_date, hora_inicio_op_obj)
        operation_end_dt = combine_date_time(selected_date, hora_fim_op_obj)
        if not current_potential_dt or not operation_end_dt: return jsonify({"message": "Erro fatal ao calcular horários."}), 500

        # Usa a DURAÇÃO TOTAL calculada
        last_possible_start_dt = operation_end_dt - timedelta(minutes=total_service_duration_minutes)

        app.logger.info(f"Verificando slots (duração {total_service_duration_minutes} min) de {current_potential_dt.time()} até {last_possible_start_dt.time()}")

        while current_potential_dt <= last_possible_start_dt:
            # Usa a DURAÇÃO TOTAL
            potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

            # Verifica se termina após o expediente
            if potential_end_dt.time() > hora_fim_op_obj and hora_fim_op_obj != time(0, 0):
                current_potential_dt += timedelta(minutes=interval_minutes)
                continue

            # Conta conflitos com agendamentos da MESMA FUNÇÃO GERAL
            overlapping_count = 0
            for busy in busy_intervals:
                if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                    overlapping_count += 1

            # Verifica se há staff disponível COM A FUNÇÃO GERAL
            if overlapping_count < available_staff_count:
                available_slots.append(current_potential_dt.strftime('%H:%M'))

            current_potential_dt += timedelta(minutes=interval_minutes)

        # 9. Finalização e Retorno (Lógica mantida)
        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"Horários disponíveis calculados ({overall_required_role}): {unique_available_slots}")
        return jsonify(unique_available_slots)

    # --- Bloco Except (Lógica mantida) ---
    except Exception as e:
        app.logger.error(f"Erro inesperado na rota: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado."}), 500

# --- Bloco de Execução Local (Lógica mantida) ---
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

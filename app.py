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
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas.")

supabase: Client = create_client(url, key)

app = Flask(__name__)
CORS(app)

DIAS_SEMANA_PT = {
    0: 'Segunda-Feira', 1: 'Terça-Feira', 2: 'Quarta-Feira',
    3: 'Quinta-Feira', 4: 'Sexta-Feira', 5: 'Sábado', 6: 'Domingo'
}

# --- Funções Auxiliares (parse_time, combine_date_time, get_required_role_for_service, determine_overall_required_role - MANTIDAS IGUAIS) ---
def parse_time(time_str: str) -> time | None:
    if not time_str: return None
    try: return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try: return datetime.strptime(time_str, '%H:%M').time()
        except ValueError: app.logger.error(f"Formato hora inválido: {time_str}."); return None
def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    if not data_obj or not tempo_obj: return None
    return datetime.combine(data_obj, tempo_obj)
def get_required_role_for_service(service_name: str) -> str | None:
    if not service_name: return None; service_name_lower = service_name.lower()
    if 'banho' in service_name_lower and 'tosa' in service_name_lower: return 'Banho e Tosa'
    elif 'tosa' in service_name_lower: return 'Groomer'
    elif 'banho' in service_name_lower: return 'Banhista'
    elif 'hidratação' in service_name_lower: return 'Banhista'
    return 'Banhista' # Padrão
def determine_overall_required_role(service_details_list: list) -> str | None:
    required_roles = set(role for service in service_details_list if (role := get_required_role_for_service(service.get('nome'))))
    if not required_roles: return None
    if 'Banho e Tosa' in required_roles: return 'Banho e Tosa'
    elif 'Groomer' in required_roles: return 'Groomer'
    elif 'Banhista' in required_roles: return 'Banhista'
    else: return None
# --- Fim Funções Auxiliares ---

@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        # 1. Obter Parâmetros (Lógica mantida)
        data_str = request.args.get('data'); servico_ids_str = request.args.get('servicoIds'); empresa_id = request.args.get('empresaId')
        if not data_str or not servico_ids_str or not empresa_id: return jsonify({"message": "Parâmetros 'data', 'servicoIds', 'empresaId' obrigatórios."}), 400
        servico_ids_list = [sid.strip() for sid in servico_ids_str.split(',') if sid.strip()]
        if not servico_ids_list: return jsonify({"message": "Pelo menos um ID de serviço deve ser fornecido."}), 400
        try: selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError: return jsonify({"message": "Formato de data inválido (Use YYYY-MM-DD)."}), 400
        if selected_date < date.today(): return jsonify({"message": "Não agendar para datas passadas."}), 400
        app.logger.info(f"Buscando: Empresa={empresa_id}, Data={selected_date}, Serviços IDs={servico_ids_list}")

        # 2. Buscar TODOS os Blocos de Horário de Funcionamento (MODIFICADO)
        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)
        if not dia_semana_nome: return jsonify({"message": "Dia da semana não configurado."}), 404

        response_hf = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .order('hora_inicio') # Ordena para processar na ordem correta (manhã -> tarde)
            .execute()

        if response_hf.error:
            app.logger.error(f"Erro Supabase ao buscar horários func.: {response_hf.error}")
            return jsonify({"message": "Erro ao buscar horários de funcionamento."}), 500
        if not response_hf.data:
            app.logger.info(f"Nenhum horário de funcionamento ativo encontrado para {dia_semana_nome}.")
            return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404

        # Processa TODOS os blocos encontrados
        operating_blocks_parsed = []
        for block_data in response_hf.data:
            start_time = parse_time(block_data.get('hora_inicio'))
            end_time = parse_time(block_data.get('hora_fim'))
            if start_time and end_time and start_time < end_time: # Verifica se são válidos e se início < fim
                operating_blocks_parsed.append({'start': start_time, 'end': end_time})
            else:
                app.logger.warning(f"Bloco de horário inválido ignorado: {block_data}")

        if not operating_blocks_parsed:
            app.logger.info("Nenhum bloco de horário válido encontrado após parse.")
            return jsonify({"message": "Nenhum horário de funcionamento válido configurado para este dia."}), 404

        app.logger.info(f"Blocos de funcionamento encontrados e válidos: {operating_blocks_parsed}")

        # 3. Buscar Detalhes de MÚLTIPLOS Serviços (Lógica mantida)
        response_sv = supabase.table('servicos').select('id, tempo_servico, nome').in_('id', servico_ids_list).eq('empresa_id', empresa_id).execute()
        if response_sv.error: return jsonify({"message": "Erro ao buscar detalhes dos serviços."}), 500
        found_ids = {str(s['id']) for s in response_sv.data}
        missing_ids = [sid for sid in servico_ids_list if sid not in found_ids]
        if not response_sv.data or missing_ids: return jsonify({"message": f"Serviço(s) inválido(s): {', '.join(missing_ids)}"}), 404
        service_details_list = response_sv.data

        # 4. Calcular DURAÇÃO TOTAL e Determinar FUNÇÃO GERAL (Lógica mantida)
        total_service_duration_minutes = 0
        for service in service_details_list:
            try: duration = int(service['tempo_servico']); total_service_duration_minutes += duration
            except (ValueError, TypeError, KeyError): return jsonify({"message": f"Duração inválida: '{service.get('nome')}'."}), 500
        if total_service_duration_minutes <= 0: return jsonify({"message": "Duração total inválida."}), 400
        overall_required_role = determine_overall_required_role(service_details_list)
        if not overall_required_role: return jsonify({"message": "Não foi possível determinar profissional."}), 500
        app.logger.info(f"Duração Total: {total_service_duration_minutes} min, Requer: {overall_required_role}")

        # 5. Contar Profissionais Disponíveis (Lógica mantida)
        response_staff = supabase.table('usuarios').select('id', count='exact').eq('empresa_id', empresa_id).eq('funcao', overall_required_role).execute()
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Staff disponível ({overall_required_role}): {available_staff_count}")
        if available_staff_count == 0: return jsonify({"message": f"Nenhum profissional ({overall_required_role}) disponível."}), 404

        # 6. Buscar Agendamentos Existentes (Lógica mantida)
        response_ag = supabase.table('agendamentos').select('id, hora, servico').eq('empresa_id', empresa_id).eq('data', data_str).execute()
        existing_appointments = response_ag.data if response_ag.data else []
        app.logger.info(f"Agendamentos existentes: {len(existing_appointments)}")

        # 7. Processar Agendamentos Existentes (Lógica mantida, usa overall_required_role)
        busy_intervals = []
        relevant_appts_count = 0
        for appt in existing_appointments:
            appt_id = appt.get('id'); appt_time_str = appt.get('hora'); appt_service_name = appt.get('servico')
            if not appt_time_str or not appt_service_name: continue
            resp_appt_svc = supabase.table('servicos').select('tempo_servico, nome').eq('empresa_id', empresa_id).eq('nome', appt_service_name).maybe_single().execute()
            if resp_appt_svc.data:
                appt_svc_details = resp_appt_svc.data
                appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))
                if appt_required_role == overall_required_role:
                    relevant_appts_count += 1
                    try:
                        appt_duration = int(appt_svc_details['tempo_servico'])
                        appt_start_time_obj = parse_time(appt_time_str)
                        if appt_start_time_obj:
                            appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                            appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                            busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt})
                    except (ValueError, TypeError, KeyError) as e: app.logger.warning(f"Erro proc. agend. {appt_id}: {e}")
            else: app.logger.warning(f"Detalhes não enc. serv. '{appt_service_name}' agend. {appt_id}.")
        app.logger.info(f"Agendamentos relevantes ({overall_required_role}): {relevant_appts_count}")

        # 8. Gerar e Verificar Slots Potenciais (MODIFICADO para iterar sobre blocos)
        available_slots = []
        interval_minutes = 15 # Intervalo entre slots (ex: 15 minutos)

        # Itera sobre cada bloco de horário de funcionamento válido encontrado
        for block in operating_blocks_parsed:
            block_start_time = block['start']
            block_end_time = block['end']
            app.logger.info(f"Processando bloco: {block_start_time} - {block_end_time}")

            current_potential_dt = combine_date_time(selected_date, block_start_time)
            operation_block_end_dt = combine_date_time(selected_date, block_end_time)

            if not current_potential_dt or not operation_block_end_dt:
                app.logger.warning(f"Erro ao combinar data/hora para o bloco {block}. Pulando bloco.")
                continue # Pula para o próximo bloco se houver erro

            # Calcula o último horário de início POSSÍVEL DENTRO DESTE BLOCO
            last_possible_start_dt_in_block = operation_block_end_dt - timedelta(minutes=total_service_duration_minutes)

            # Loop while para gerar slots DENTRO do bloco atual
            while current_potential_dt <= last_possible_start_dt_in_block:
                potential_end_dt = current_potential_dt + timedelta(minutes=total_service_duration_minutes)

                # VERIFICAÇÃO IMPORTANTE: O serviço deve TERMINAR DENTRO OU NO LIMITE do bloco atual
                # Compara apenas as partes de hora (time objects)
                if potential_end_dt.time() > block_end_time and block_end_time != time(0, 0):
                     # Se terminar DEPOIS do fim do bloco, este slot não é válido DENTRO deste bloco.
                     # Como o loop já verifica <= last_possible_start_dt_in_block,
                     # esta condição extra garante que não "vaze" para o próximo bloco.
                     # Podemos simplesmente parar de verificar slots para ESTE bloco, pois os próximos também excederão.
                     # No entanto, a condição do while já deve cuidar disso. Vamos avançar o ponteiro.
                     # Vamos confiar na condição do while e avançar. Se der problema, revisitamos.
                     pass # A condição do while cuida disso

                # Conta conflitos (Lógica mantida)
                overlapping_count = 0
                for busy in busy_intervals:
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1

                # Verifica disponibilidade (Lógica mantida)
                if overlapping_count < available_staff_count:
                    available_slots.append(current_potential_dt.strftime('%H:%M'))

                # Avança para o próximo slot potencial
                current_potential_dt += timedelta(minutes=interval_minutes)
            # Fim do loop while para este bloco
        # Fim do loop for para todos os blocos

        # 9. Finalização e Retorno (Lógica mantida)
        unique_available_slots = sorted(list(set(available_slots)))
        app.logger.info(f"Horários disponíveis FINAIS ({overall_required_role}): {unique_available_slots}")
        return jsonify(unique_available_slots)

    except Exception as e:
        app.logger.error(f"Erro inesperado GERAL: {e}", exc_info=True)
        return jsonify({"message": "Ocorreu um erro interno inesperado."}), 500

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5000, debug=True)

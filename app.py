import os
from dotenv import load_dotenv
from flask import Flask, request, jsonify
from supabase import create_client, Client
from datetime import datetime, time, timedelta, date
from flask_cors import CORS
import logging # Adicionar logging

load_dotenv()

# Configuração básica de logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")

if not url or not key:
    # Usar logging em vez de print para erros críticos também
    logging.critical("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")
    raise EnvironmentError("Erro Crítico: SUPABASE_URL e SUPABASE_KEY não encontradas. Verifique seu arquivo .env")

supabase: Client = create_client(url, key)

app = Flask(__name__)
# Usar o logger do Flask
app.logger.setLevel(logging.INFO) # Definir o nível de logging para o Flask
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
        # Tenta primeiro com segundos
        return datetime.strptime(time_str, '%H:%M:%S').time()
    except ValueError:
        try:
            # Tenta sem segundos
            return datetime.strptime(time_str, '%H:%M').time()
        except ValueError:
            app.logger.error(f"Formato de hora inválido recebido: {time_str}. Use HH:MM:SS ou HH:MM.")
            return None

def combine_date_time(data_obj: date, tempo_obj: time) -> datetime | None:
    if not data_obj or not tempo_obj: return None
    try:
        return datetime.combine(data_obj, tempo_obj)
    except TypeError:
        app.logger.error(f"Erro ao combinar data {data_obj} e hora {tempo_obj}.")
        return None


def get_required_role_for_service(service_name: str) -> str | None:
    if not service_name: return None
    service_name_lower = service_name.lower()
    # Tornar a verificação mais robusta
    if 'tosa' in service_name_lower:
        return 'Groomer'
    # Assumir que 'banho' e 'hidratação' são feitos pelo 'Banhista'
    elif 'banho' in service_name_lower or 'hidratação' in service_name_lower:
         return 'Banhista'
    # Adicionar um log se nenhuma correspondência for encontrada, mas ainda retornar um padrão
    app.logger.warning(f"Não foi possível determinar a função EXATA para o serviço '{service_name}'. Verificando se é serviço de banho/hidratação para Banhista.")
    # Considerar um retorno padrão ou None se a lógica for mais complexa
    # Por ora, vamos manter Banhista como padrão, mas com aviso
    return 'Banhista' # Ou talvez retornar None e tratar isso depois? Por enquanto, Banhista.


@app.route('/api/horarios-disponiveis', methods=['GET'])
def get_available_slots():
    try:
        app.logger.info("Recebida requisição para /api/horarios-disponiveis")

        data_str = request.args.get('data')
        servico_id = request.args.get('servicoId')
        empresa_id = request.args.get('empresaId')

        if not data_str or not servico_id or not empresa_id:
            app.logger.error("Erro: Parâmetros ausentes na requisição (data, servicoId, empresaId).")
            return jsonify({"message": "Parâmetros 'data', 'servicoId' e 'empresaId' são obrigatórios."}), 400

        try:
            selected_date = datetime.strptime(data_str, '%Y-%m-%d').date()
        except ValueError:
            app.logger.error(f"Erro: Formato de data inválido '{data_str}'. Use YYYY-MM-DD.")
            return jsonify({"message": "Formato de data inválido. Use YYYY-MM-DD."}), 400

        if selected_date < date.today():
             app.logger.warning(f"Tentativa de agendamento para data passada: {selected_date}")
             # Retornar lista vazia em vez de erro, pois a UI pode permitir selecionar datas passadas
             # return jsonify({"message": "Não é possível agendar para datas passadas."}), 400
             return jsonify([]), 200 # Retorna lista vazia se a data for passada


        app.logger.info(f"Buscando horários para Empresa: {empresa_id}, Data: {selected_date}, Serviço ID: {servico_id}")

        dia_semana_num = selected_date.weekday()
        dia_semana_nome = DIAS_SEMANA_PT.get(dia_semana_num)

        if not dia_semana_nome:
            # Isso não deve acontecer com a definição atual de DIAS_SEMANA_PT
            app.logger.error(f"Dia da semana {dia_semana_num} não mapeado em DIAS_SEMANA_PT.")
            # Retornar lista vazia em vez de erro 404
            # return jsonify({"message": "Dia da semana inválido."}), 400
            return jsonify([]), 200

        app.logger.info(f"Dia da semana: {dia_semana_nome} ({dia_semana_num})")

        # --- ALTERAÇÃO 1: Buscar TODOS os intervalos de funcionamento para o dia ---
        response_horarios = supabase.table('horarios_funcionamento')\
            .select('hora_inicio, hora_fim')\
            .eq('empresa_id', empresa_id)\
            .eq('dia_semana', dia_semana_nome)\
            .eq('ativo', True)\
            .execute()

        if not response_horarios.data:
            app.logger.info(f"Nenhum horário de funcionamento ATIVO encontrado para {dia_semana_nome} na empresa {empresa_id}.")
            # Retornar lista vazia se fechado
            # return jsonify({"message": f"Petshop fechado ou sem horário configurado para {dia_semana_nome}."}), 404
            return jsonify([]), 200

        # Processar e validar os intervalos encontrados
        operating_intervals = []
        for interval_data in response_horarios.data:
            hora_inicio_obj = parse_time(interval_data.get('hora_inicio'))
            hora_fim_obj = parse_time(interval_data.get('hora_fim'))

            # Validar se os horários foram parseados corretamente e se o início é antes do fim
            if hora_inicio_obj and hora_fim_obj and hora_inicio_obj < hora_fim_obj:
                operating_intervals.append({'start': hora_inicio_obj, 'end': hora_fim_obj})
                app.logger.info(f"Intervalo de funcionamento válido encontrado: {hora_inicio_obj} - {hora_fim_obj}")
            else:
                 app.logger.warning(f"Intervalo de funcionamento inválido ou mal formado ignorado: {interval_data}. Início={hora_inicio_obj}, Fim={hora_fim_obj}")

        if not operating_intervals:
            app.logger.warning(f"Nenhum horário de funcionamento VÁLIDO encontrado para {dia_semana_nome} na empresa {empresa_id} após validação.")
            # Retornar lista vazia
            # return jsonify({"message": f"Nenhum horário de funcionamento válido configurado para {dia_semana_nome}."}), 404
            return jsonify([]), 200

        # Ordenar intervalos por hora de início (bom para clareza e pode otimizar a lógica futura)
        operating_intervals.sort(key=lambda x: x['start'])
        # --- FIM DA ALTERAÇÃO 1 ---


        # Buscar detalhes do serviço (duração e nome para determinar a função)
        response_servico = supabase.table('servicos')\
            .select('tempo_servico, nome')\
            .eq('id', servico_id)\
            .eq('empresa_id', empresa_id)\
            .maybe_single()\
            .execute()

        if not response_servico.data:
            app.logger.warning(f"Serviço com ID {servico_id} não encontrado para a empresa {empresa_id}.")
            # Retornar lista vazia
            # return jsonify({"message": "Serviço não encontrado."}), 404
            return jsonify([]), 200

        service_details = response_servico.data
        try:
            # Garantir que tempo_servico seja um inteiro positivo
            service_duration_minutes = int(service_details['tempo_servico'])
            if service_duration_minutes <= 0:
                 raise ValueError("Duração do serviço deve ser positiva.")
        except (ValueError, TypeError, KeyError) as e:
             app.logger.error(f"Valor inválido, ausente ou não positivo para 'tempo_servico' no serviço {servico_id}: {e}. Detalhes: {service_details}")
             # Retornar lista vazia
             # return jsonify({"message": "Duração do serviço inválida ou não configurada corretamente."}), 500
             return jsonify([]), 200


        service_name = service_details.get('nome', 'Nome Desconhecido')
        required_role = get_required_role_for_service(service_name)

        if not required_role:
             # Se get_required_role_for_service retornar None no futuro
             app.logger.error(f"Não foi possível determinar a função necessária para o serviço '{service_name}' (ID: {servico_id}).")
             # Retornar lista vazia
             # return jsonify({"message": f"Não foi possível determinar o tipo de profissional necessário para '{service_name}'."}), 500
             return jsonify([]), 200

        app.logger.info(f"Detalhes do serviço '{service_name}': Duração={service_duration_minutes} min, Requer Função='{required_role}'")


        # Verificar quantos funcionários com a função necessária estão disponíveis
        response_staff = supabase.table('usuarios')\
            .select('id', count='exact')\
            .eq('empresa_id', empresa_id)\
            .eq('funcao', required_role)\
            .eq('ativo', True) # Adicionar verificação se o usuário está ativo
            .execute()

        # Usar .count diretamente é mais seguro
        available_staff_count = response_staff.count if response_staff.count is not None else 0
        app.logger.info(f"Total de profissionais ATIVOS com função '{required_role}': {available_staff_count}")

        if available_staff_count == 0:
            app.logger.info(f"Nenhum profissional ({required_role}) ativo encontrado para realizar este serviço.")
            # Retornar lista vazia
            # return jsonify({"message": f"Nenhum profissional ({required_role}) disponível para realizar este serviço."}), 404
            return jsonify([]), 200


        # Buscar agendamentos existentes *para a data selecionada* na empresa
        response_agendamentos = supabase.table('agendamentos')\
            .select('id, hora, servico, status') # Buscar status também pode ser útil
            .eq('empresa_id', empresa_id)\
            .eq('data', data_str)\
            .neq('status', 'Cancelado') # Ignorar agendamentos cancelados
            .execute()

        existing_appointments = response_agendamentos.data if response_agendamentos.data else []
        app.logger.info(f"Total de agendamentos existentes (não cancelados) na data {data_str}: {len(existing_appointments)}")


        # Montar lista de intervalos ocupados por profissionais da *mesma função*
        busy_intervals = []
        processed_appts_count = 0
        relevant_appts_count = 0

        # Cache para detalhes de serviços já consultados (otimização)
        service_details_cache = {}

        for appt in existing_appointments:
            appt_id = appt.get('id')
            appt_time_str = appt.get('hora')
            appt_service_name = appt.get('servico') # Nome do serviço do agendamento

            if not appt_time_str or not appt_service_name:
                app.logger.warning(f"Agendamento existente {appt_id} sem hora ou nome de serviço. Ignorando.")
                continue

            processed_appts_count += 1
            appt_svc_details = None
            appt_required_role = None
            appt_duration = None

            # Verificar cache primeiro
            if appt_service_name in service_details_cache:
                appt_svc_details = service_details_cache[appt_service_name]
            else:
                # Buscar detalhes do serviço do agendamento existente
                resp_appt_svc = supabase.table('servicos')\
                    .select('tempo_servico, nome')\
                    .eq('empresa_id', empresa_id)\
                    .eq('nome', appt_service_name)\
                    .maybe_single()\
                    .execute()
                if resp_appt_svc.data:
                    appt_svc_details = resp_appt_svc.data
                    # Armazenar no cache
                    service_details_cache[appt_service_name] = appt_svc_details
                else:
                     app.logger.warning(f"Não encontrou detalhes do serviço '{appt_service_name}' para o agendamento existente {appt_id}. Agendamento será ignorado na contagem de ocupação.")
                     continue # Pula para o próximo agendamento se não encontrar o serviço

            # Se temos os detalhes (do cache ou da busca)
            if appt_svc_details:
                appt_required_role = get_required_role_for_service(appt_svc_details.get('nome'))
                try:
                    appt_duration = int(appt_svc_details['tempo_servico'])
                    if appt_duration <= 0: raise ValueError("Duração inválida")
                except (ValueError, TypeError, KeyError) as e:
                    app.logger.warning(f"Erro ao obter duração do serviço '{appt_service_name}' para agendamento {appt_id}: {e}. Agendamento ignorado na contagem.")
                    continue # Pula se a duração for inválida

                # Verificar se a função do agendamento existente é a mesma da que estamos buscando
                if appt_required_role == required_role:
                    relevant_appts_count += 1
                    appt_start_time_obj = parse_time(appt_time_str)

                    if appt_start_time_obj and appt_duration:
                        appt_start_dt = combine_date_time(selected_date, appt_start_time_obj)
                        if appt_start_dt: # Verifica se combine_date_time funcionou
                            appt_end_dt = appt_start_dt + timedelta(minutes=appt_duration)
                            busy_intervals.append({'start': appt_start_dt, 'end': appt_end_dt, 'id': appt_id}) # Adiciona ID para debug
                            # app.logger.debug(f"Intervalo ocupado relevante (ID:{appt_id}, Serviço:{appt_service_name}, Função:{required_role}): {appt_start_dt} - {appt_end_dt}")
                        else:
                             app.logger.warning(f"Não foi possível combinar data/hora para agendamento {appt_id} ({appt_start_time_obj}). Ignorando.")
                    else:
                        app.logger.warning(f"Hora inválida ({appt_time_str}) ou duração inválida ({appt_duration}) para agendamento relevante {appt_id}. Ignorando.")
                # else:
                    # app.logger.debug(f"Agendamento {appt_id} (Serviço: {appt_service_name}) ignorado, requer função '{appt_required_role}', diferente de '{required_role}'.")

        app.logger.info(f"Processados {processed_appts_count} agendamentos existentes. {len(busy_intervals)} intervalos ocupados relevantes encontrados para a função '{required_role}'.")


        # --- ALTERAÇÃO 2: Gerar horários iterando sobre CADA intervalo de funcionamento ---
        available_slots = []
        interval_minutes = 15 # Intervalo entre os slots potenciais (pode ser configurável)

        app.logger.info(f"Verificando slots a cada {interval_minutes} min dentro dos {len(operating_intervals)} intervalos de funcionamento para o serviço de {service_duration_minutes} min.")

        # Iterar sobre cada bloco de horário de funcionamento (manhã, tarde, etc.)
        for interval in operating_intervals:
            hora_inicio_intervalo = interval['start']
            hora_fim_intervalo = interval['end']

            app.logger.debug(f"Processando intervalo de funcionamento: {hora_inicio_intervalo.strftime('%H:%M')} - {hora_fim_intervalo.strftime('%H:%M')}")

            # Definir o início e fim do bloco atual em datetime
            current_potential_dt = combine_date_time(selected_date, hora_inicio_intervalo)
            interval_end_dt = combine_date_time(selected_date, hora_fim_intervalo)

            if not current_potential_dt or not interval_end_dt:
                app.logger.error(f"Erro fatal ao combinar data/hora para o intervalo {hora_inicio_intervalo}-{hora_fim_intervalo}. Pulando este intervalo.")
                continue

            # Calcular o último horário possível para INICIAR o serviço DENTRO deste intervalo
            # O serviço deve terminar ATÉ a hora de fim do intervalo
            last_possible_start_dt_interval = interval_end_dt - timedelta(minutes=service_duration_minutes)

            app.logger.debug(f"-> Início da varredura no intervalo: {current_potential_dt.strftime('%H:%M')}")
            app.logger.debug(f"-> Último início possível neste intervalo: {last_possible_start_dt_interval.strftime('%H:%M')}")

            # Loop para gerar slots potenciais dentro do intervalo atual
            while current_potential_dt <= last_possible_start_dt_interval:
                potential_end_dt = current_potential_dt + timedelta(minutes=service_duration_minutes)

                # Não precisamos mais da checagem `potential_end_dt.time() > hora_fim_intervalo`
                # porque a condição do while `current_potential_dt <= last_possible_start_dt_interval` já garante isso.

                # Verificar sobreposição com agendamentos existentes da mesma função
                overlapping_count = 0
                for busy in busy_intervals:
                    # Verifica se há intersecção entre [current_potential_dt, potential_end_dt) e [busy['start'], busy['end'])
                    if current_potential_dt < busy['end'] and potential_end_dt > busy['start']:
                        overlapping_count += 1
                        # app.logger.debug(f"Slot potencial {current_potential_dt.strftime('%H:%M')} - {potential_end_dt.strftime('%H:%M')} tem sobreposição com Agendamento ID {busy['id']} ({busy['start'].strftime('%H:%M')} - {busy['end'].strftime('%H:%M')})")


                # Se o número de sobreposições for menor que o número de funcionários disponíveis, o slot está livre
                if overlapping_count < available_staff_count:
                    slot_time_str = current_potential_dt.strftime('%H:%M')
                    available_slots.append(slot_time_str)
                    # app.logger.debug(f"-> Slot DISPONÍVEL encontrado: {slot_time_str} (Sobreposições: {overlapping_count}, Staff: {available_staff_count})")
                # else:
                    # app.logger.debug(f"-> Slot OCUPADO: {current_potential_dt.strftime('%H:%M')} (Sobreposições: {overlapping_count}, Staff: {available_staff_count})")


                # Avançar para o próximo slot potencial
                current_potential_dt += timedelta(minutes=interval_minutes)

            app.logger.debug(f"Fim da varredura para o intervalo {hora_inicio_intervalo.strftime('%H:%M')} - {hora_fim_intervalo.strftime('%H:%M')}")
        # --- FIM DA ALTERAÇÃO 2 ---

        # Remover duplicados (caso intervalos gerem o mesmo slot, improvável com passo de 15min) e ordenar
        unique_available_slots = sorted(list(set(available_slots)))

        app.logger.info(f"Total de horários disponíveis únicos calculados para '{required_role}' em {selected_date}: {len(unique_available_slots)}")
        app.logger.debug(f"Horários disponíveis: {unique_available_slots}")

        return jsonify(unique_available_slots), 200 # Retornar 200 OK com a lista (pode ser vazia)

    except Exception as e:
        # Captura qualquer outra exceção não prevista
        app.logger.error(f"Erro inesperado na rota /api/horarios-disponiveis: {e}", exc_info=True) # Logar o stack trace
        return jsonify({"message": "Ocorreu um erro interno inesperado ao buscar horários. Tente novamente mais tarde."}), 500


if __name__ == '__main__':
    # Habilitar debug do Flask apenas em desenvolvimento
    app.run(host='0.0.0.0', port=5000, debug=os.environ.get("FLASK_DEBUG", "false").lower() == "true")

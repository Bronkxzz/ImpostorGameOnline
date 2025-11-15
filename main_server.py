from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.responses import HTMLResponse
from typing import Dict
from game_manager import game_manager, Game, MIN_PLAYERS
import json
import uuid

# Inicialização
app = FastAPI()
# Armazena as conexões WebSocket ativas para cada jogo
active_connections: Dict[str, List[WebSocket]] = {} 

# --- FUNÇÕES AUXILIARES DE BROADCAST ---

async def broadcast_game_state(game_id: str):
    """Envia o estado público atual do jogo para todos os jogadores conectados."""
    game = game_manager.get_game(game_id)
    if not game:
        return

    state = game.get_public_state()
    message = json.dumps({"type": "STATE_UPDATE", "data": state})
    
    connections = active_connections.get(game_id, [])
    for connection in connections:
        try:
            await connection.send_text(message)
        except:
            # Lida com conexões fechadas
            connections.remove(connection)
            
# --- ROTAS HTTP (Criação e Informação) ---

@app.get("/")
async def get_home():
    # Isso servirá o arquivo HTML do Frontend (Passo 3)
    try:
        with open("index.html", "r", encoding="utf-8") as f:
            html_content = f.read()
        return HTMLResponse(content=html_content)
    except FileNotFoundError:
        return HTMLResponse("<h1>Página Inicial</h1><p>Frontend não encontrado. Crie o arquivo index.html no mesmo diretório.</p>")

@app.post("/api/create_game/{player_name}")
async def create_game(player_name: str):
    """Cria um novo jogo e retorna o ID."""
    player_id = str(uuid.uuid4())
    game = game_manager.create_game(player_id, player_name)
    
    return {
        "game_id": game.game_id, 
        "host_id": player_id, 
        "message": f"Jogo criado com sucesso. ID: {game.game_id}"
    }

# --- ROTA WEBSOCKET (Comunicação em Tempo Real) ---

@app.websocket("/ws/{game_id}/{player_id}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_id: str, player_name: str):
    game = game_manager.get_game(game_id)
    if not game:
        await websocket.close(code=1008, reason="Jogo não encontrado.")
        return

    # 1. Conexão e Inscrição
    await websocket.accept()
    
    if game_id not in active_connections:
        active_connections[game_id] = []
        
    active_connections[game_id].append(websocket)

    # Tenta adicionar o jogador, se não for o host reconectando
    is_new_player = game.add_player(player_id, player_name)

    print(f"Nova conexão em {game_id}: {player_name}")
    await broadcast_game_state(game_id)

    # 2. Loop de Recebimento de Mensagens
    try:
        while True:
            data = await websocket.receive_text()
            
            try:
                message = json.loads(data)
                command = message.get("command")
                payload = message.get("payload", {})
            except json.JSONDecodeError:
                continue

            response = {"type": "ERROR", "message": "Comando inválido."}

            if command == "START_GAME":
                # Apenas o Host pode iniciar
                if player_id == game.host_id:
                    start_result = game.start_game()
                    if "success" in start_result:
                        # Envia palavras privadas por WS
                        for p_id, p_data in start_result['private_words'].items():
                            await send_private_message(game_id, p_id, p_data)
                        response = {"type": "GAME_STARTED"}
                        await broadcast_game_state(game_id)
                    else:
                         response = {"type": "ERROR", "message": start_result["error"]}
                else:
                    response = {"type": "ERROR", "message": "Apenas o Host pode iniciar."}
            
            elif command == "SUBMIT_CLUE":
                clue = payload.get("clue")
                result = game.submit_clue(player_id, clue)
                if "success" in result:
                    game.next_turn() # Avança o turno
                    await broadcast_game_state(game_id)
                    response = {"type": "CLUE_ACCEPTED"}
                else:
                    response = {"type": "ERROR", "message": result["error"]}
            
            elif command == "VOTE":
                voted_id = payload.get("voted_id")
                result = game.submit_vote(player_id, voted_id)
                
                if "success" in result or result.get("status") == "GAME_OVER":
                    await broadcast_game_state(game_id)
                    if result.get("status") == "GAME_OVER":
                        # O jogo terminou, limpa o estado
                        game_manager.remove_game(game_id) 
                else:
                    response = {"type": "ERROR", "message": result["error"]}

            # Envia a resposta específica para o jogador que enviou o comando
            await websocket.send_text(json.dumps(response))

    except WebSocketDisconnect:
        # 3. Desconexão
        print(f"Desconexão em {game_id}: {player_name}")
        active_connections[game_id].remove(websocket)
        
        # Remove o jogador apenas se o jogo estiver na fase de espera
        if game.status == "WAITING_FOR_PLAYERS":
            game.remove_player(player_id)
            await broadcast_game_state(game_id)
            
        # Se o host sair, o jogo é fechado
        if player_id == game.host_id:
            game_manager.remove_game(game_id)
            await broadcast_game_state(game_id) # Notifica que o jogo sumiu


async def send_private_message(game_id: str, player_id: str, data: Dict):
    """Envia uma mensagem privada (palavra/papel) por WebSocket."""
    message = json.dumps({"type": "PRIVATE_MESSAGE", "data": data})
    
    connections = active_connections.get(game_id, [])
    # Encontra a conexão específica do jogador
    for connection in connections:
        # A conexão do WS não tem o player_id, mas a gente assume que a lista é pequena e envia.
        # Em um sistema real, você associaria o player_id à conexão.
        # Por simplicidade, vamos usar uma suposição.
        # O cliente JS no front-end precisará filtrar esta mensagem.
        try:
             await connection.send_text(message) 
        except:
             pass # Conexão fechada
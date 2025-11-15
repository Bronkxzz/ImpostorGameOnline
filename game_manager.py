import json
import random
import uuid
import time
from collections import Counter
from typing import List, Dict, Union, Optional, Any

# --- CONSTANTES ---
MIN_PLAYERS = 3
DEFAULT_WORD_PAIRS = [
    {"inocente": "Cachorro", "impostor": "Gato"},
    {"inocente": "Banana", "impostor": "Maçã"},
    {"inocente": "Internet", "impostor": "Intranet"},
    {"inocente": "Pizza", "impostor": "Hambúrguer"},
    {"inocente": "Café", "impostor": "Chá"},
]

# --- CLASSES AUXILIARES (MODELOS DE DADOS) ---
class GameConfig:
    def __init__(self, clue_time: int = 60, vote_time: int = 90, rounds_per_player: int = 1):
        self.clue_time = clue_time # Segundos para cada jogador dar a pista
        self.vote_time = vote_time # Segundos para a fase de votação
        self.rounds_per_player = rounds_per_player # Quantas vezes cada inocente dá pista

class Player:
    def __init__(self, player_id: str, name: str):
        self.id = player_id
        self.name = name
        self.role: Optional[str] = None # "IMPOSTOR" ou "INOCENTE"
        self.word: Optional[str] = None
        self.has_given_clue: bool = False
        self.has_voted: bool = False

    def to_public_dict(self) -> Dict[str, Any]:
        return {"id": self.id, "name": self.name}

# ----------------------------------------------------------------
# CLASSE: Game (Gerencia o estado de UMA partida)
# ----------------------------------------------------------------

class Game:
    def __init__(self, host_id: str, host_name: str, words: List[Dict], config: GameConfig):
        self.game_id = str(uuid.uuid4())[:8]  # ID único para o link do site
        self.players: Dict[str, Player] = {host_id: Player(host_id, host_name)} # {player_id: Player_object}
        self.host_id = host_id
        self.words = words
        self.config = config
        
        self.status = "WAITING_FOR_PLAYERS" 
        self.impostor_id: Optional[str] = None
        self.word_pair: Optional[Dict[str, str]] = None
        
        self.current_round = 0
        self.current_turn_index = -1 # Índice do jogador atual na lista ordenada
        self.players_turn_order: List[str] = [] # Ordem dos jogadores no turno
        self.clues: List[Dict[str, str]] = [] # [{player_name: "Pista"}]
        self.votes: Dict[str, str] = {}  # {voter_id: voted_id}
        
        self.timer_start_time: Optional[float] = None
        self.timer_duration: int = 0
        self.timer_paused: bool = False
        
        self.results: Dict[str, Any] = {}

    def get_public_state(self, requester_id: Optional[str] = None) -> Dict[str, Any]:
        """Retorna o estado do jogo para ser exibido na interface de todos."""
        
        current_player_name = self.players[self.players_turn_order[self.current_turn_index]].name if self.status == 'IN_PROGRESS' and self.players_turn_order and self.current_turn_index >= 0 else None
        current_player_id = self.players_turn_order[self.current_turn_index] if self.status == 'IN_PROGRESS' and self.players_turn_order and self.current_turn_index >= 0 else None
        
        remaining_time = 0
        if self.timer_start_time and not self.timer_paused:
            elapsed = time.time() - self.timer_start_time
            remaining_time = max(0, self.timer_duration - int(elapsed))

        return {
            "id": self.game_id,
            "status": self.status,
            "players": [p.to_public_dict() for p in self.players.values()], # Nomes dos jogadores
            "player_count": len(self.players),
            "min_players": MIN_PLAYERS,
            "config": {
                "clue_time": self.config.clue_time,
                "vote_time": self.config.vote_time,
                "rounds_per_player": self.config.rounds_per_player,
            },
            "clues": self.clues,
            "current_round": self.current_round,
            "current_turn": current_player_name,
            "current_player_id": current_player_id, # Usado pelo frontend para saber de quem é a vez
            "timer": remaining_time,
            "total_players_to_vote": len(self.players) if self.status == 'VOTING' else 0,
            "votes_count": len(self.votes),
            "results": self.results if self.status == 'FINISHED' else {},
        }
    
    def get_private_player_data(self, player_id: str) -> Optional[Dict[str, Any]]:
        """Retorna dados privados (palavra, papel) para um jogador específico."""
        player = self.players.get(player_id)
        if player and player.role and player.word:
            return {"word": player.word, "role": player.role}
        return None

    def add_player(self, player_id: str, name: str) -> bool:
        if self.status != "WAITING_FOR_PLAYERS" or player_id in self.players:
            return False
        self.players[player_id] = Player(player_id, name)
        return True

    def remove_player(self, player_id: str) -> bool:
        if player_id not in self.players:
            return False
        
        # Não permite sair durante o jogo a menos que seja o Host (para encerrar)
        if self.status != "WAITING_FOR_PLAYERS" and player_id != self.host_id:
            return False
        
        del self.players[player_id]
        
        # Se o host sair, o jogo deve ser encerrado pelo GameManager
        if player_id == self.host_id:
            return True # Sinaliza que o GameManager deve remover o jogo
        
        return True

    def start_game(self) -> Dict[str, Any]:
        """Inicia a partida, distribuindo as palavras e o impostor."""
        if len(self.players) < MIN_PLAYERS:
            return {"error": f"Requer no mínimo {MIN_PLAYERS} jogadores."}
        if self.status != "WAITING_FOR_PLAYERS":
            return {"error": "O jogo já começou ou está em outro estado."}

        self.status = "IN_PROGRESS"
        self.word_pair = random.choice(self.words)
        
        # Define a ordem dos turnos
        self.players_turn_order = list(self.players.keys())
        random.shuffle(self.players_turn_order)

        # Escolhe o impostor
        self.impostor_id = random.choice(self.players_turn_order)

        # Distribui palavras e papéis
        private_words_data = {}
        for p_id in self.players_turn_order:
            player = self.players[p_id]
            if p_id == self.impostor_id:
                player.role = "IMPOSTOR"
                player.word = self.word_pair['impostor']
            else:
                player.role = "INOCENTE"
                player.word = self.word_pair['inocente']
            private_words_data[p_id] = {"word": player.word, "role": player.role}
        
        self.current_round = 1
        self.current_turn_index = -1 # Para o next_turn() começar do 0
        
        self._start_next_player_turn() # Inicia o primeiro turno

        return {"success": True, "private_words_data": private_words_data}
    
    def _start_next_player_turn(self):
        """Prepara para o próximo jogador dar sua pista."""
        self.current_turn_index += 1

        # Checa se todos os jogadores deram pistas nesta rodada
        if self.current_turn_index >= len(self.players_turn_order):
            self.current_round += 1
            self.current_turn_index = 0 # Reinicia o ciclo para a próxima rodada
            
            # Se atingiu o número máximo de rodadas, vai para votação
            if self.current_round > self.config.rounds_per_player:
                self.status = "VOTING"
                self.timer_duration = self.config.vote_time
                self.timer_start_time = time.time()
                return

        # Inicia o temporizador para o jogador atual dar a pista
        self.status = "IN_PROGRESS" # Garante o status se veio da votação ou aguarda
        self.timer_duration = self.config.clue_time
        self.timer_start_time = time.time()
        
        # Reseta o status de "já deu pista" para a nova rodada
        current_player_id = self.players_turn_order[self.current_turn_index]
        self.players[current_player_id].has_given_clue = False

    def submit_clue(self, player_id: str, clue: str) -> Dict[str, Any]:
        """Processa a pista de um jogador."""
        if self.status != "IN_PROGRESS":
            return {"error": "Não é fase de dar pistas."}
        
        current_player_id = self.players_turn_order[self.current_turn_index]
        
        if player_id != current_player_id:
            return {"error": "Não é sua vez."}
        
        player = self.players[player_id]
        if player.has_given_clue:
            return {"error": "Você já deu sua pista nesta rodada."}

        # Validação de pista (uma palavra e não a palavra real/falsa)
        clue_upper = clue.upper().strip()
        if not clue_upper or len(clue_upper.split()) > 1:
            return {"error": "A pista deve ser uma palavra única."}
        if self.word_pair and (clue_upper == self.word_pair['inocente'].upper() or clue_upper == self.word_pair['impostor'].upper()):
            return {"error": "A pista não pode ser a palavra secreta."}

        self.clues.append({"player_name": player.name, "clue": clue_upper})
        player.has_given_clue = True
        
        # Avança para o próximo turno após a pista
        self._start_next_player_turn()
        
        return {"success": True}

    def submit_vote(self, voter_id: str, voted_id: str) -> Dict[str, Any]:
        """Registra um voto."""
        if self.status != "VOTING":
            return {"error": "A votação não está em andamento."}
        if voter_id not in self.players or voted_id not in self.players:
            return {"error": "Jogador votante ou votado inválido."}
        if voter_id == voted_id:
            return {"error": "Você não pode votar em si mesmo."}
        
        player = self.players[voter_id]
        if player.has_voted:
            return {"error": "Você já votou."}
        
        self.votes[voter_id] = voted_id
        player.has_voted = True

        if len(self.votes) == len(self.players):
            # Votação finalizada
            return self.process_votes()

        return {"success": True, "votos_restantes": len(self.players) - len(self.votes)}

    def process_votes(self) -> Dict[str, Any]:
        """Calcula o resultado final da votação."""
        self.status = "FINISHED"
        self.timer_paused = True # Pausa o temporizador

        # Se houver jogadores que não votaram (tempo esgotado)
        for p_id in self.players.keys():
            if p_id not in self.votes:
                self.votes[p_id] = "ABSTENÇÃO" # Marca como abstenção para contabilizar
        
        vote_counts = Counter(self.votes.values())
        
        winner = "IMPOSTOR" # Padrão, em caso de empate ou não votação clara
        result_message = ""
        
        if not vote_counts or (len(vote_counts) == 1 and "ABSTENÇÃO" in vote_counts):
            result_message = f"Ninguém votou ou todos se abstiveram! O Impostor ({self.players[self.impostor_id].name}) escapou."
            winner = "IMPOSTOR"
        else:
            # Encontra o jogador mais votado (excluindo abstenções se houver outros votos)
            most_voted_tally = [item for item in vote_counts.most_common() if item[0] != "ABSTENÇÃO"]
            
            if not most_voted_tally: # Apenas abstenções
                 result_message = f"Ninguém votou! O Impostor ({self.players[self.impostor_id].name}) escapou."
                 winner = "IMPOSTOR"
            else:
                most_voted_id, count = most_voted_tally[0]
                most_voted_name = self.players[most_voted_id].name
                
                # Checa se há empate para o mais votado
                tied_votes = [item for item in most_voted_tally if item[1] == count]

                if len(tied_votes) > 1:
                    result_message = f"Empate na votação! O Impostor ({self.players[self.impostor_id].name}) escapou."
                    winner = "IMPOSTOR"
                elif most_voted_id == self.impostor_id:
                    result_message = f"SUCESSO! {most_voted_name} foi eliminado e ERA o Impostor! Inocentes vencem."
                    winner = "INOCENTES"
                else:
                    result_message = f"FRACASSO! {most_voted_name} foi eliminado, mas era INOCENTE. O Impostor ({self.players[self.impostor_id].name}) venceu."

        self.results = {
            "winner": winner,
            "message": result_message,
            "impostor_name": self.players[self.impostor_id].name,
            "real_word": self.word_pair['inocente'],
            "fake_word": self.word_pair['impostor'],
            "all_clues": self.clues,
            "votes_tally": {self.players.get(k, k).name if k != "ABSTENÇÃO" else "ABSTENÇÃO": v for k,v in vote_counts.items()}
        }
        
        return {"status": "GAME_OVER", "results": self.results}
    
    def check_timer(self) -> Optional[Dict[str, Any]]:
        """Verifica o temporizador e avança o jogo se esgotado."""
        if self.timer_start_time and not self.timer_paused:
            elapsed = time.time() - self.timer_start_time
            if elapsed >= self.timer_duration:
                # Timer esgotado!
                if self.status == "IN_PROGRESS":
                    # O jogador atual não deu a pista a tempo. Pula.
                    player_id = self.players_turn_order[self.current_turn_index]
                    if not self.players[player_id].has_given_clue:
                        self.clues.append({"player_name": self.players[player_id].name, "clue": "(Pista Perdida - Tempo Esgotado)"})
                        self.players[player_id].has_given_clue = True
                    self._start_next_player_turn()
                    return {"event": "TURN_SKIPPED"}
                elif self.status == "VOTING":
                    # Tempo de votação esgotado. Processa os votos atuais.
                    return self.process_votes()
        return None


# ----------------------------------------------------------------
# CLASSE: GameManager (Gerencia TODAS as partidas ativas)
# ----------------------------------------------------------------

class GameManager:
    def __init__(self, word_path: str = 'palavras.json'):
        self.active_games: Dict[str, Game] = {}
        self.load_words(word_path)

    def load_words(self, path: str):
        """Carrega as palavras do arquivo JSON (reutilizando a lógica do bot)."""
        try:
            with open(path, 'r', encoding='utf-8') as f:
                self.word_pairs = json.load(f)
            print(f"✅ {len(self.word_pairs)} pares de palavras carregados de {path}.")
        except FileNotFoundError:
            self.word_pairs = DEFAULT_WORD_PAIRS
            print(f"⚠️ Arquivo 'palavras.json' não encontrado. Usando palavras padrão.")
        except json.JSONDecodeError:
             self.word_pairs = DEFAULT_WORD_PAIRS
             print("❌ Erro ao ler palavras.json! Arquivo corrompido. Usando palavras padrão.")

    def create_game(self, host_id: str, host_name: str, config: GameConfig) -> Game:
        """Cria um novo objeto Game e o adiciona aos jogos ativos."""
        new_game = Game(host_id, host_name, self.word_pairs, config)
        self.active_games[new_game.game_id] = new_game
        return new_game

    def get_game(self, game_id: str) -> Optional[Game]:
        """Retorna um objeto Game pelo ID."""
        return self.active_games.get(game_id)
    
    def remove_game(self, game_id: str):
        """Remove um jogo da lista de ativos (limpeza)."""
        if game_id in self.active_games:
            del self.active_games[game_id]
            return True
        return False

# A instância global do gerenciador será usada pelo servidor
game_manager = GameManager()
import json
import random
import uuid
from collections import Counter
from typing import List, Dict, Union, Optional

# --- CONSTANTES ---
MIN_PLAYERS = 3
DEFAULT_WORD_PAIRS = [
    {"inocente": "Cachorro", "impostor": "Gato"},
    {"inocente": "Banana", "impostor": "Maçã"},
    {"inocente": "Internet", "impostor": "Intranet"},
]

# ----------------------------------------------------------------
# CLASSE: Game (Gerencia o estado de UMA partida)
# ----------------------------------------------------------------

class Game:
    def __init__(self, host_id: str, host_name: str, words: List[Dict]):
        self.game_id = str(uuid.uuid4())[:8]  # ID único para o link do site
        self.players: Dict[str, str] = {host_id: host_name} # {player_id: player_name}
        self.host_id = host_id
        self.words = words
        
        self.status = "WAITING_FOR_PLAYERS" 
        self.impostor_id: Optional[str] = None
        self.word_pair: Optional[Dict[str, str]] = None
        
        self.current_turn_index = -1
        self.clues: Dict[str, str] = {} # {player_id: "Pista"}
        self.votes: Dict[str, str] = {}  # {voter_id: voted_id}

    def get_public_state(self) -> Dict:
        """Retorna o estado do jogo para ser exibido na interface de todos."""
        current_player_name = self.players.get(self.players_list[self.current_turn_index]) if self.status == 'IN_PROGRESS' and self.players_list else None
        
        return {
            "id": self.game_id,
            "status": self.status,
            "players": list(self.players.values()), # Nomes dos jogadores
            "player_count": len(self.players),
            "min_players": MIN_PLAYERS,
            "clues": list(self.clues.values()),
            "current_turn": current_player_name,
            "current_player_id": self.players_list[self.current_turn_index] if self.players_list and self.current_turn_index >= 0 else None,
            "votes_count": len(self.votes),
            "total_players_to_vote": len(self.players) if self.status == 'VOTING' else 0,
            # Resultados (apenas após o fim)
            "results": {}, 
        }

    @property
    def players_list(self) -> List[str]:
        """Retorna a lista de IDs dos jogadores em ordem."""
        return list(self.players.keys())

    def add_player(self, player_id: str, name: str) -> bool:
        if self.status != "WAITING_FOR_PLAYERS" or player_id in self.players:
            return False
        self.players[player_id] = name
        return True

    def remove_player(self, player_id: str) -> bool:
        if self.status != "WAITING_FOR_PLAYERS" and player_id != self.host_id:
            # Não permite sair durante o jogo, a menos que seja o Host (para encerrar)
            return False
        if player_id in self.players:
            del self.players[player_id]
            return True
        return False

    def start_game(self) -> Dict[str, str]:
        """Inicia a partida, distribuindo as palavras e o impostor."""
        if len(self.players) < MIN_PLAYERS:
            return {"error": f"Requer no mínimo {MIN_PLAYERS} jogadores."}

        self.status = "IN_PROGRESS"
        self.word_pair = random.choice(self.words)
        self.impostor_id = random.choice(self.players_list)
        self.current_turn_index = 0
        self.clues = {} 

        # Envia a palavra privada para cada jogador
        private_words = {}
        for p_id, p_name in self.players.items():
            if p_id == self.impostor_id:
                private_words[p_id] = {"word": self.word_pair['impostor'], "role": "IMPOSTOR"}
            else:
                private_words[p_id] = {"word": self.word_pair['inocente'], "role": "INOCENTE"}
        
        return {"success": True, "private_words": private_words}

    def next_turn(self):
        """Avança para o próximo jogador ou para a fase de votação."""
        
        # Se a pista do jogador atual não foi dada, pula ele.
        current_player_id = self.players_list[self.current_turn_index]
        if current_player_id not in self.clues:
            self.clues[current_player_id] = f"(Pista perdida por {self.players[current_player_id]})"

        self.current_turn_index += 1
        
        if self.current_turn_index >= len(self.players):
            # Todos deram suas pistas, inicia a votação
            self.status = "VOTING"
            self.votes = {}
            return {"status": "VOTING_STARTED"}
        
        return {"status": "NEXT_TURN"}

    def submit_clue(self, player_id: str, clue: str) -> Dict:
        """Processa a pista de um jogador."""
        
        current_player_id = self.players_list[self.current_turn_index]
        
        if player_id != current_player_id:
            return {"error": "Não é sua vez."}
        if player_id in self.clues:
            return {"error": "Você já deu sua pista."}

        # Validação simples (pode ser melhorada depois)
        if not clue or len(clue.split()) > 1:
            return {"error": "A pista deve ser uma palavra única."}

        self.clues[player_id] = clue.upper().strip()
        
        return {"success": True}

    def submit_vote(self, voter_id: str, voted_id: str) -> Dict:
        """Registra um voto."""
        if self.status != "VOTING":
            return {"error": "A votação não está em andamento."}
        if voter_id not in self.players:
            return {"error": "Você não está no jogo."}
        if voted_id not in self.players:
            return {"error": "O jogador votado não existe."}
        if voter_id == voted_id:
            return {"error": "Você não pode votar em si mesmo."}
        if voter_id in self.votes:
            return {"error": "Você já votou."}
        
        self.votes[voter_id] = voted_id

        if len(self.votes) == len(self.players):
            # Votação finalizada
            return self.process_votes()

        return {"success": True, "votos_restantes": len(self.players) - len(self.votes)}

    def process_votes(self) -> Dict:
        """Calcula o resultado final da votação."""
        self.status = "FINISHED"
        
        if not self.votes:
            result_message = f"Ninguém votou! O Impostor ({self.players[self.impostor_id]}) escapou."
            winner = "IMPOSTOR"
        else:
            vote_counts = Counter(self.votes.values())
            
            # Obtém o ID do mais votado
            most_voted_id, count = vote_counts.most_common(1)[0]
            
            most_voted_name = self.players[most_voted_id]
            
            if most_voted_id == self.impostor_id:
                result_message = f"SUCESSO! {most_voted_name} foi eliminado e ERA o Impostor! Inocentes vencem."
                winner = "INOCENTES"
            else:
                result_message = f"FRACASSO! {most_voted_name} foi eliminado, mas era INOCENTE. O Impostor ({self.players[self.impostor_id]}) venceu."
                winner = "IMPOSTOR"

        # Adiciona o resultado final ao estado público
        self.results = {
            "winner": winner,
            "message": result_message,
            "impostor_name": self.players[self.impostor_id],
            "real_word": self.word_pair['inocente'],
            "fake_word": self.word_pair['impostor'],
            "clues": self.clues,
            "votes_tally": {self.players[k]:v for k,v in vote_counts.items()} # Para mostrar a contagem
        }
        
        return {"status": "GAME_OVER", "results": self.results}
    
    def get_private_data(self, player_id: str) -> Dict:
        """Retorna os dados privados do jogador (papel e palavra)."""
        if player_id == self.impostor_id:
            role = "IMPOSTOR"
            word = self.word_pair['impostor']
        else:
            role = "INOCENTE"
            word = self.word_pair['inocente']
            
        return {"role": role, "word": word}

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

    def create_game(self, host_id: str, host_name: str) -> Game:
        """Cria um novo objeto Game e o adiciona aos jogos ativos."""
        new_game = Game(host_id, host_name, self.word_pairs)
        self.active_games[new_game.game_id] = new_game
        return new_game

    def get_game(self, game_id: str) -> Optional[Game]:
        """Retorna um objeto Game pelo ID."""
        return self.active_games.get(game_id)
    
    def get_game_state(self, game_id: str) -> Optional[Dict]:
        """Retorna o estado público do jogo."""
        game = self.get_game(game_id)
        return game.get_public_state() if game else None

    def remove_game(self, game_id: str):
        """Remove um jogo da lista de ativos (limpeza)."""
        if game_id in self.active_games:
            del self.active_games[game_id]
            return True
        return False


# A instância global do gerenciador será usada pelo servidor
game_manager = GameManager()

# ----------------------------------------------------------------
# CÓDIGO DE EXEMPLO (O servidor usará isso)
# ----------------------------------------------------------------

if __name__ == '__main__':
    # Exemplo de como usar a lógica (simulando um jogo)
    
    # 1. Criação
    game = game_manager.create_game(host_id="p1", host_name="Bronkxzz")
    print(f"Jogo criado com ID: {game.game_id}. Status: {game.status}")

    # 2. Inscrição
    game.add_player("p2", "Alice")
    game.add_player("p3", "Bob")
    print(f"Jogadores após inscrição: {game.players}")

    # 3. Início
    result = game.start_game()
    print(f"\nInício do jogo. Resultado: {result['success']}")
    print(f"Impostor ID: {game.impostor_id}. Palavra real: {game.word_pair['inocente']}")
    
    # 4. Turno 1
    print(f"\nTurno atual: {game.players[game.players_list[game.current_turn_index]]}")
    game.submit_clue("p1", "verde") # Bronkxzz dá pista
    game.next_turn()
    
    # 5. Turno 2
    print(f"Turno atual: {game.players[game.players_list[game.current_turn_index]]}")
    game.submit_clue("p2", "voa") # Alice dá pista
    game.next_turn()
    
    # 6. Turno 3
    print(f"Turno atual: {game.players[game.players_list[game.current_turn_index]]}")
    game.submit_clue("p3", "fruta") # Bob dá pista
    result_turn = game.next_turn()
    
    # 7. Votação
    print(f"\nStatus após turnos: {game.status}")
    game.submit_vote("p1", "p3") # Bronkxzz vota em Bob
    game.submit_vote("p2", "p3") # Alice vota em Bob
    result_vote = game.submit_vote("p3", "p2") # Bob vota em Alice (termina o jogo)
    
    # 8. Fim
    print(f"\nStatus final: {game.status}")
    print(f"Resultado final: {result_vote['results']['message']}")
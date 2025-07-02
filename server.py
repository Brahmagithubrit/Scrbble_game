from flask import Flask, render_template, request, redirect
from flask_socketio import SocketIO, emit
import random
import threading
import time

app = Flask(__name__)
app.config['SECRET_KEY'] = 'secret_key'
socketio = SocketIO(app, cors_allowed_origins="*", async_mode='eventlet')

connected_users = {}
users_scores = {}
drawing_order = []
current_drawer_index = 0

WORDS = ["apple", "car", "book", "fish", "pizza", "train", "cloud", "shoe", "house", "tree", "moon", "star", "flower", "guitar", "camera", "phone"]

current_game = {
    "drawer": None,
    "wordOptions": [],
    "chosenWord": None,
    "phase": "lobby", 
    "round": 1,
    "word_choice_timer": None,
    "drawing_timer": None,
    "drawing_ended": False
}

@app.route('/')
def intro():
    return render_template("intro.html")

@app.route('/home')
def home():
    return render_template("index.html")

@socketio.on('connect')
def handle_connect():
    print(f'Client connected: {request.sid}')

@socketio.on('register')
def handle_register(username):
    connected_users[request.sid] = username
    users_scores[username] = users_scores.get(username, 0)
    
    user_list = []
    for user in connected_users.values():
        user_list.append({
            "username": user,
            "score": users_scores.get(user, 0)
        })
    
    emit('user_list', user_list, broadcast=True)
    print(f'User registered: {username}')

@socketio.on('disconnect')
def handle_disconnect():
    if request.sid in connected_users:
        username = connected_users[request.sid]
        del connected_users[request.sid]
        print(f'User disconnected: {username}')
        
        user_list = []
        for user in connected_users.values():
            user_list.append({
                "username": user,
                "score": users_scores.get(user, 0)
            })
        
        emit('user_list', user_list, broadcast=True)

@socketio.on('start_game')
def start_game():
    global drawing_order, current_drawer_index
    
    if len(connected_users) < 2:
        emit('error', {'message': 'Need at least 2 players to start'})
        return
    
  
    emit('clear_guesses', broadcast=True)
    
    if not drawing_order or current_drawer_index >= len(drawing_order):
        drawing_order = list(connected_users.values())
        random.shuffle(drawing_order) 
        current_drawer_index = 0
    
    drawer_name = drawing_order[current_drawer_index]
    word_options = random.sample(WORDS, 3)
    
    current_game["drawer"] = drawer_name
    current_game["wordOptions"] = word_options
    current_game["chosenWord"] = None
    current_game["phase"] = "choosing"
    current_game["drawing_ended"] = False
    
    emit("game_start", {
        "drawer": drawer_name,
        "wordOptions": word_options,
        "phase": "choosing",
        "timer": 10,
        "round": current_game["round"]
    }, broadcast=True)
    
    print(f'Game started, drawer: {drawer_name}, Round: {current_game["round"]}')
    
    def word_choice_timeout():
        time.sleep(10)
        if current_game["phase"] == "choosing" and not current_game["chosenWord"]:
            random_word = random.choice(current_game["wordOptions"])
            current_game["chosenWord"] = random_word
            current_game["phase"] = "drawing"
            
            socketio.emit("start_drawing", {
                "word": random_word,
                "timer": 60,
                "auto_selected": True
            })
            
            print(f"Auto-selected word: {random_word}")
            
            start_drawing_timer()
    
    timer_thread = threading.Thread(target=word_choice_timeout)
    timer_thread.daemon = True
    timer_thread.start()

@socketio.on("word_chosen")
def word_chosen(word):
    if word not in current_game["wordOptions"]:
        return
    
    if current_game["phase"] != "choosing":
        return
    
    current_game["chosenWord"] = word
    current_game["phase"] = "drawing"
    print(f"{current_game['drawer']} chose word: {word}")
    
    emit("start_drawing", {
        "word": word,
        "timer": 60,
        "auto_selected": False
    }, broadcast=True)
    
    start_drawing_timer()

def start_drawing_timer():
    def drawing_timeout():
        time.sleep(60)
        if current_game["phase"] == "drawing":
            current_game["drawing_ended"] = True
            current_game["phase"] = "finished"
            
            global current_drawer_index
            current_drawer_index += 1
            current_game["round"] += 1
            
            socketio.emit("round_ended", {
                "word": current_game["chosenWord"],
                "drawer": current_game["drawer"],
                "next_round": current_drawer_index < len(drawing_order)
            })
            
            print(f"Drawing time ended. Word was: {current_game['chosenWord']}")
    
    timer_thread = threading.Thread(target=drawing_timeout)
    timer_thread.daemon = True
    timer_thread.start()

@socketio.on("draw_data")
def handle_draw_data(data):
    if (request.sid in connected_users and 
        connected_users[request.sid] == current_game["drawer"] and
        current_game["phase"] == "drawing" and
        not current_game["drawing_ended"]):
        emit("draw_data", data, broadcast=True, include_self=False)

@socketio.on("submit_guess")
def handle_guess(data):
    username = data.get("username")
    guess = data.get("guess", "").strip()
    
    if not guess or not current_game["chosenWord"]:
        return
    
    if username == current_game["drawer"]:
        return
    
    if current_game["drawing_ended"] or current_game["phase"] != "drawing":
        return
    
    correct = guess.lower() == current_game["chosenWord"].lower()
    
    if correct:
        users_scores[username] = users_scores.get(username, 0) + 100
        
        user_list = []
        for user in connected_users.values():
            user_list.append({
                "username": user,
                "score": users_scores.get(user, 0)
            })
        
        emit('user_list', user_list, broadcast=True)
        
        display_guess = "*" * len(guess)
    else:
        display_guess =  guess
    
    emit("guess_result", {
        "username": username,
        "guess": display_guess,
        "correct": correct,
        "score": users_scores.get(username, 0)
    }, broadcast=True)
    
    print(f'{username} guessed "{guess}" - {"Correct" if correct else "Wrong"}')

@socketio.on("clear_canvas")
def handle_clear_canvas():
    if (request.sid in connected_users and 
        connected_users[request.sid] == current_game["drawer"] and
        current_game["phase"] == "drawing" and
        not current_game["drawing_ended"]):
        emit("clear_canvas", broadcast=True, include_self=False)

if __name__ == '__main__':
    import eventlet
    eventlet.monkey_patch()
    socketio.run(app, host='0.0.0.0', port=10000)

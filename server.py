# CITS3002 2021 Assignment
#
# This file implements a basic server that allows a single client to play a
# single game with no other participants, and very little error checking.
#
# Any other clients that connect during this time will need to wait for the
# first client's game to complete.
#
# Your task will be to write a new server that adds all connected clients into
# a pool of players. When enough players are available (two or more), the server
# will create a game with a random sample of those players (no more than
# tiles.PLAYER_LIMIT players will be in any one game). Players will take turns
# in an order determined by the server, continuing until the game is finished
# (there are less than two players remaining). When the game is finished, if
# there are enough players available the server will start a new game with a
# new selection of clients.

import socket
import sys
import tiles
from threading import Thread
import random
import time
import select
import collections
from os import system, name

PLAYERS_PER_GAME = 4
tileHistory = []
tokenHistory = []
originalOrder = []
eliminatedPlayers = []

class Player():
    def __init__(self, connection, address, idnum):
        self.connection = connection
        self.host, self.port = address
        self.idnum = idnum
        self.messages = collections.deque()

    def __eq__(self, other):
        return self.idnum == other.idnum

    def getName(self):
        return '{}:{}'.format(self.host, self.port)


def boradcastCurrentPlayer(clients, currentPlayer):
    msg = tiles.MessagePlayerTurn(currentPlayer.idnum).pack()
    for client in clients:
        client.connection.send(msg)


def boradcastPlayerEliminated(clients, player):
    global eliminatedPlayers
    msg = tiles.MessagePlayerEliminated(player.idnum).pack()
    eliminatedPlayers.append(msg)
    for client in clients:
        client.connection.send(msg)


def boradcastPlayerLeave(clients, player):
    for client in clients:
        msg = tiles.MessagePlayerLeft(player.idnum).pack()
        client.connection.send(msg)


def boradcastGameStart(clients):
    for client in clients:
        msg = tiles.MessageGameStart().pack()
        client.connection.send(msg)


def boradcastPositionUpdates(clients, updates):    
    for client in clients:
        for update in updates:
            client.connection.send(update.pack())

def broadcastPlaceSuccessful(clients, msg):
    global tileHistory
    tileHistory.append(msg)
    for client in clients:
        client.connection.send(msg.pack())

def boradcastCountdown(clients):
    for client in clients:
        client.connection.send(tiles.MessageCountdown().pack())

def broadcastUpdates(lobby, queue, board, current):
    global tokenHistory
    live_idnums = get_live_idnums(lobby)
    positionupdates, eliminated = board.do_player_movement(
    live_idnums)

    tokenHistory.extend(positionupdates)

    boradcastPositionUpdates(queue + lobby, positionupdates)

    lobby.append(lobby.pop(0))

    if current.idnum in eliminated:
        boradcastPlayerEliminated(queue + lobby, current)
        queue.append(current)
        lobby.remove(current)

def logging(queue: list, lobby: list):
    while True:
        # for windows
        if name == 'nt':
            _ = system('cls')

        # for mac and linux(here, os.name is 'posix')
        else:
            _ = system('clear')

        print("Connected Users [{}]".format(len(lobby + queue)))
        for client in [*lobby, *queue]:
            print("\t" + client.getName())

        print("Lobby [{}/{}]".format(len(lobby), tiles.PLAYER_LIMIT))
        for client in lobby:
            print("\t" + client.getName())

        print("Queue [{}]".format(len(queue)))
        for client in queue:
            print("\t" + client.getName())

        time.sleep(1)


def update_status(queue: list, lobby: list):
    while True:
        activeSockets = []
        for client in [*queue, *lobby]:
            activeSockets.append(client.connection)

        try:
            ready, _, _ = select.select(activeSockets, [], [], 0)

            for clientConnection in ready:
                message = clientConnection.recv(4096)

                for client in lobby:
                    if client.connection == clientConnection:
                        lobbyIndex = lobby.index(client)
                        lobby[lobbyIndex].messages.appendleft(message)
                        if not message:
                            lobby.remove(client)
                            boradcastPlayerEliminated([*queue, *lobby], client)
                            boradcastPlayerLeave([*queue, *lobby], client)
                        break

                for client in queue:
                    if client.connection == clientConnection:
                        queueIndex = queue.index(client)
                        queue[queueIndex].messages.appendleft(message)
                        if not message:
                            queue.remove(client)
                            boradcastPlayerLeave([*queue, *lobby], client)
                        break
        except:
            continue


def update_queue(queue, lobby, sock):
    global tileHistory
    global tokenHistory
    global originalOrder
    global eliminatedPlayers
    # constantly check for new clients
    idnum = 0
    while True:
        # handle new connection
        connection, client_address = sock.accept()

        # add player to queue
        newPlayer = Player(connection, client_address, idnum)
        idnum += 1

        # send messages
        connection.send(tiles.MessageWelcome(newPlayer.idnum).pack())

        # make sure all clients know other clients
        for player in queue + lobby:
            player.connection.send(tiles.MessagePlayerJoined(
                newPlayer.getName(), newPlayer.idnum).pack())

            newPlayer.connection.send(tiles.MessagePlayerJoined(
                player.getName(), player.idnum).pack())

        queue.append(newPlayer)

        # send cumilative updates to joining client
        if len(lobby) != 0:
            boradcastGameStart([newPlayer])
            # notify client of all players
            for client in originalOrder:
                boradcastCurrentPlayer([newPlayer], client)

            # notify of current player
            boradcastCurrentPlayer([newPlayer], lobby[0])

            # notify of all board updates
            for msg in tileHistory:
                newPlayer.connection.send(msg.pack())

            for msg in tokenHistory:
                newPlayer.connection.send(msg.pack())

            for msg in eliminatedPlayers:
                newPlayer.connection.send(msg)


def lobby_thread(queue: list, lobby: list):
    global originalOrder
    while (len(queue) < 2):
        continue

    boradcastCountdown(queue + lobby)
    time.sleep(2)

    lobbySize = min([len(queue), tiles.PLAYER_LIMIT])

    for _ in range(lobbySize):
        playerIndex = random.randrange(0, len(queue))
        player = queue.pop(playerIndex)
        lobby.append(player)
    
    originalOrder.extend(lobby)
    return


def get_live_idnums(lobby: list):
    live_idnums = []
    for client in lobby:
        live_idnums.append(client.idnum)

    return live_idnums


def game_thread(queue: list, lobby: list):
    global tokenHistory
    # notify all players of start
    boradcastGameStart(queue + lobby)        

    # give all players a random hand
    for player in lobby:
        boradcastCurrentPlayer(lobby + queue, player)
        for _ in range(tiles.HAND_SIZE):
            tileid = tiles.get_random_tileid()
            msg = tiles.MessageAddTileToHand(tileid).pack()
            player.connection.send(msg)

    # start main game loop
    board = tiles.Board()
    currentPlayer = None
    while len(lobby) != 1:
        # start next turn
        if currentPlayer is not lobby[0]:
            currentPlayer = lobby[0]
            boradcastCurrentPlayer(queue + lobby, currentPlayer)
            
        try:
            chunk = currentPlayer.messages.popleft()

            if not chunk:
                raise Exception("Client Disconnected")

            buffer = bytearray()
            buffer.extend(chunk)
            msg, consumed = tiles.read_message_from_bytearray(buffer)
            if not consumed:
                raise Exception("Unable To Read Message")

            buffer = buffer[consumed:]
            
            # sent by the player to put a tile onto the board (in all turns except
            # their second)
            placingTile = isinstance(msg, tiles.MessagePlaceTile)
            selectingToken = isinstance(msg, tiles.MessageMoveToken)
            
            if placingTile or selectingToken:
                if placingTile:
                    if board.set_tile(msg.x, msg.y, msg.tileid, msg.rotation, msg.idnum):
                        # notify client that placement was successful
                        broadcastPlaceSuccessful(queue + lobby, msg)

                        # pickup a new tile
                        tileid = tiles.get_random_tileid()
                        tilemsg = tiles.MessageAddTileToHand(tileid).pack()
                        currentPlayer.connection.send(tilemsg)

                        broadcastUpdates(lobby, queue, board, currentPlayer)

                elif selectingToken:
                    if not board.have_player_position(msg.idnum):
                        if board.set_player_start_position(msg.idnum, msg.x, msg.y, msg.position):
                            tokenHistory.append(msg)
                            broadcastUpdates(lobby, queue, board, currentPlayer)
        except:
            continue

    queue.extend(lobby)
    lobby.clear()


# create a TCP/IP socket
sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)

# listen on all network interfaces
server_address = ('', 30020)
sock.bind(server_address)

sock.listen(5)

playerQueue = []
playerLobby = []

# constantly handle incomming connections
connectionThread = Thread(target=update_queue, args=(playerQueue, playerLobby, sock))
connectionThread.start()

# evaluate health of connections
ststusThread = Thread(target=update_status, args=(playerQueue, playerLobby))
ststusThread.start()

loggingThread = Thread(target=logging, args=(playerQueue, playerLobby))
loggingThread.start()

while True:
    # wait for players to fill the lobby
    # time.sleep(5)

    lobbyFormationThread = Thread(
        target=lobby_thread, args=(playerQueue, playerLobby))
    lobbyFormationThread.start()
    lobbyFormationThread.join()

    # start game
    gameThread = Thread(target=game_thread, args=(playerQueue, playerLobby))
    gameThread.start()
    gameThread.join()
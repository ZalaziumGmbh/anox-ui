# import socketio
# import logging
# import sys

# from open_webui.apps.webui.models.users import Users
# from open_webui.env import (
#     ENABLE_WEBSOCKET_SUPPORT,
#     WEBSOCKET_MANAGER,
#     WEBSOCKET_REDIS_URL,
# )
# from open_webui.utils.utils import decode_token
# from open_webui.apps.socket.utils import AsyncRedisDict

# from open_webui.env import (
#     GLOBAL_LOG_LEVEL,
#     SRC_LOG_LEVELS,
# )

import asyncio
import socketio
import logging
import time

from open_webui.apps.webui.models.users import Users
from open_webui.env import (
    ENABLE_WEBSOCKET_SUPPORT,
    WEBSOCKET_MANAGER,
    WEBSOCKET_REDIS_URL,
    GLOBAL_LOG_LEVEL,
    SRC_LOG_LEVELS,
)
from open_webui.utils.utils import decode_token
from open_webui.apps.socket.utils import AsyncRedisDict


logging.basicConfig(level=GLOBAL_LOG_LEVEL)
log = logging.getLogger(__name__)
log.setLevel(SRC_LOG_LEVELS.get("SOCKET", logging.INFO))

if WEBSOCKET_MANAGER == "redis":
    mgr = socketio.AsyncRedisManager(WEBSOCKET_REDIS_URL)
    sio = socketio.AsyncServer(
        cors_allowed_origins=[],
        async_mode="asgi",
        client_manager=mgr,
        transports=(
            ["polling", "websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]
        ),
        allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
        always_connect=True,
    )
else:
    sio = socketio.AsyncServer(
        cors_allowed_origins=[],
        async_mode="asgi",
        transports=(
            ["polling", "websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]
        ),
        allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
        always_connect=True,
    )

app = socketio.ASGIApp(
    sio,
    socketio_path="/ws/socket.io",
)

# Initialize SESSION_POOL, USER_POOL, USAGE_POOL
if WEBSOCKET_MANAGER == "redis":
    SESSION_POOL = AsyncRedisDict(
        "open-webui:session_pool", redis_url=WEBSOCKET_REDIS_URL
    )
    USER_POOL = AsyncRedisDict("open-webui:user_pool", redis_url=WEBSOCKET_REDIS_URL)
    USAGE_POOL = AsyncRedisDict("open-webui:usage_pool", redis_url=WEBSOCKET_REDIS_URL)
else:
    SESSION_POOL = {}
    USER_POOL = {}
    USAGE_POOL = {}

TIMEOUT_DURATION = 3  # Define your timeout duration

# Helper functions


async def add_session(sid, user_id):
    if WEBSOCKET_MANAGER == "redis":
        await SESSION_POOL.__setitem__(sid, user_id)
        user_sids = await USER_POOL.get(user_id, [])
        user_sids.append(sid)
        await USER_POOL.__setitem__(user_id, user_sids)
    else:
        SESSION_POOL[sid] = user_id
        USER_POOL.setdefault(user_id, []).append(sid)


async def remove_session(sid):
    if WEBSOCKET_MANAGER == "redis":
        user_id = await SESSION_POOL.get(sid)
        if user_id:
            await SESSION_POOL.__delitem__(sid)
            user_sids = await USER_POOL.get(user_id, [])
            user_sids = [_sid for _sid in user_sids if _sid != sid]
            if user_sids:
                await USER_POOL.__setitem__(user_id, user_sids)
            else:
                await USER_POOL.__delitem__(user_id)
    else:
        user_id = SESSION_POOL.get(sid)
        if user_id:
            del SESSION_POOL[sid]
            user_sids = USER_POOL.get(user_id, [])
            user_sids = [_sid for _sid in user_sids if _sid != sid]
            if user_sids:
                USER_POOL[user_id] = user_sids
            else:
                del USER_POOL[user_id]


async def get_user_count():
    if WEBSOCKET_MANAGER == "redis":
        keys = await USER_POOL.keys()
        return len(keys)
    else:
        return len(USER_POOL)


async def get_models_in_use():
    if WEBSOCKET_MANAGER == "redis":
        # Get all keys matching the pattern "USAGE_POOL:*"
        keys = await USAGE_POOL.redis.keys("USAGE_POOL:*")
        models_in_use = set()
        for key in keys:
            # Assuming keys are formatted as "USAGE_POOL:{model_id}:{sid}"
            parts = key.split(":")
            if len(parts) >= 2:
                model_id = parts[1]
                models_in_use.add(model_id)
        return list(models_in_use)
    else:
        return list(USAGE_POOL.keys())


# Event handlers


@sio.event
async def connect(sid, environ, auth):
    user = None
    if auth and "token" in auth and "client_id" in auth:
        data = decode_token(auth["token"])

        if data and "id" in data:
            user = Users.get_user_by_id(data["id"])

        if user and auth["client_id"] == str(user.id):
            await add_session(sid, user.id)
            await sio.enter_room(sid, user.id)

            log.info(f"User {user.name}({user.id}) connected with session ID {sid}")

            user_count = await get_user_count()
            await sio.emit("user-count", {"count": user_count})
            await sio.emit("usage", {"models": await get_models_in_use()})

            return True  # Accept the connection

    log.warning(f"Connection rejected for sid {sid}")
    return False  # Reject the connection


@sio.on("user-join")
async def user_join(sid, data):
    log.info("user-join event received")
    auth = data.get("auth")
    if not auth or "token" not in auth or "client_id" not in auth:
        return

    data = await decode_token(auth["token"])
    if data is None or "id" not in data:
        return

    user = Users.get_user_by_id(data["id"])
    if not user:
        return

    if auth["client_id"] != str(user.id):
        return

    await add_session(sid, user.id)
    await sio.enter_room(sid, user.id)

    log.info(f"User {user.name}({user.id}) joined with session ID {sid}")

    user_count = await get_user_count()
    await sio.emit("user-count", {"count": user_count})
    await sio.emit("usage", {"models": await get_models_in_use()})


@sio.on("user-count")
async def user_count(sid):
    count = await get_user_count()
    await sio.emit("user-count", {"count": count})


@sio.on("usage")
async def usage(sid, data):
    model_id = data["model"]
    if WEBSOCKET_MANAGER == "redis":
        key = f"USAGE_POOL:{model_id}:{sid}"
        # Set the key with an expiration time
        await USAGE_POOL.redis.set(key, 1, ex=TIMEOUT_DURATION)
    else:
        current_time = int(time.time())
        USAGE_POOL.setdefault(model_id, {})
        USAGE_POOL[model_id][sid] = {"updated_at": current_time}

    # Broadcast the usage data to all clients
    models_in_use = await get_models_in_use()
    await sio.emit("usage", {"models": models_in_use})


@sio.event
async def disconnect(sid):
    user_id = (
        await SESSION_POOL.get(sid)
        if WEBSOCKET_MANAGER == "redis"
        else SESSION_POOL.get(sid)
    )
    if user_id:
        await remove_session(sid)
        await sio.leave_room(sid, user_id)
        log.info(f"User {user_id} disconnected with session ID {sid}")

        # Update user count
        user_count = await get_user_count()
        await sio.emit("user-count", {"count": user_count})
    else:
        log.warning(f"Unknown session ID {sid} disconnected")


# Event emitter functions


def get_event_emitter(request_info):
    async def __event_emitter__(event_data):
        client_id = request_info.get("client_id")
        if not client_id:
            log.warning("No client_id in request_info")
            return

        await sio.emit(
            "chat-events",
            {
                "chat_id": request_info["chat_id"],
                "message_id": request_info["message_id"],
                "data": event_data,
            },
            room=client_id,
        )

    return __event_emitter__


def get_event_call(request_info):
    async def __event_call__(event_data):
        client_id = request_info.get("client_id")
        if not client_id:
            log.warning("No client_id in request_info")
            return None

        response = await sio.call(
            "chat-events",
            {
                "chat_id": request_info["chat_id"],
                "message_id": request_info["message_id"],
                "data": event_data,
            },
            to=client_id,
        )
        return response

    return __event_call__


# Periodic usage pool cleanup


async def periodic_usage_pool_cleanup():
    while True:
        now = int(time.time())
        if WEBSOCKET_MANAGER == "redis":
            # Redis handles key expiration, so we can emit updated usage info
            models_in_use = await get_models_in_use()
            await sio.emit("usage", {"models": models_in_use})
        else:
            for model_id, connections in list(USAGE_POOL.items()):
                # Creating a list of sids to remove if they have timed out
                expired_sids = [
                    sid
                    for sid, details in connections.items()
                    if now - details["updated_at"] > TIMEOUT_DURATION
                ]

                for sid in expired_sids:
                    del connections[sid]

                if not connections:
                    log.debug(f"Cleaning up model {model_id} from usage pool")
                    del USAGE_POOL[model_id]
                else:
                    USAGE_POOL[model_id] = connections

            # Emit updated usage information after cleaning
            models_in_use = await get_models_in_use()
            await sio.emit("usage", {"models": models_in_use})

        await asyncio.sleep(TIMEOUT_DURATION)


# logging.basicConfig(stream=sys.stdout, level=GLOBAL_LOG_LEVEL)
# log = logging.getLogger(__name__)
# log.setLevel(SRC_LOG_LEVELS["SOCKET"])


# if WEBSOCKET_MANAGER == "redis":
#     mgr = socketio.AsyncRedisManager(WEBSOCKET_REDIS_URL)
#     sio = socketio.AsyncServer(
#         cors_allowed_origins=[],
#         async_mode="asgi",
#         client_manager=mgr,
#         transports=(
#             ["polling", "websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]
#         ),
#         allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
#         always_connect=True,
#     )
# else:
#     sio = socketio.AsyncServer(
#         cors_allowed_origins=[],
#         async_mode="asgi",
#         transports=(
#             ["polling", "websocket"] if ENABLE_WEBSOCKET_SUPPORT else ["polling"]
#         ),
#         allow_upgrades=ENABLE_WEBSOCKET_SUPPORT,
#         always_connect=True,
#     )

# app = socketio.ASGIApp(
#     sio,
#     socketio_path="/ws/socket.io",
# )

# # Initialize RedisDict instances
# SESSION_POOL = AsyncRedisDict("open-webui:session_pool", redis_url=WEBSOCKET_REDIS_URL)
# USER_POOL = AsyncRedisDict("open-webui:user_pool", redis_url=WEBSOCKET_REDIS_URL)
# USAGE_POOL = AsyncRedisDict("open-webui:usage_pool", redis_url=WEBSOCKET_REDIS_URL)

# # Timeout duration in seconds
# TIMEOUT_DURATION = 3


# # Helper functions
# async def add_session(sid, user_id):
#     await SESSION_POOL.__setitem__(sid, user_id)
#     user_sids = await USER_POOL.get(user_id, [])
#     user_sids.append(sid)
#     await USER_POOL.__setitem__(user_id, user_sids)


# async def remove_session(sid):
#     user_id = await SESSION_POOL.get(sid)
#     if user_id:
#         await SESSION_POOL.__delitem__(sid)
#         user_sids = await USER_POOL.get(user_id, [])
#         user_sids = [_sid for _sid in user_sids if _sid != sid]
#         if user_sids:
#             await USER_POOL.__setitem__(user_id, user_sids)
#         else:
#             await USER_POOL.__delitem__(user_id)


# async def get_user_count():
#     return await USER_POOL.__len__()


# async def get_models_in_use():
#     # Get all keys matching the pattern "USAGE_POOL:*"
#     keys = await USAGE_POOL.redis.keys("USAGE_POOL:*")
#     models_in_use = set()
#     for key in keys:
#         # Assuming keys are formatted as "USAGE_POOL:{model_id}:{sid}"
#         parts = key.split(":")
#         if len(parts) >= 2:
#             model_id = parts[1]
#             models_in_use.add(model_id)
#     return list(models_in_use)


# # Event Handlers


# @sio.event
# async def connect(sid, environ, auth):
#     user = None
#     if auth and "token" in auth and "client_id" in auth:
#         data = await decode_token(auth["token"])

#         if data and "id" in data:
#             user = Users.get_user_by_id(data["id"])

#         if user and auth["client_id"] == str(user.id):
#             await add_session(sid, user.id)
#             await sio.enter_room(sid, user.id)

#             log.info(f"User {user.name}({user.id}) connected with session ID {sid}")

#             user_count = await get_user_count()
#             await sio.emit("user-count", {"count": user_count})
#             await sio.emit("usage", {"models": await get_models_in_use()})

#             return True  # Accept the connection

#     log.warning(f"Connection rejected for sid {sid}")
#     return False  # Reject the connection


# @sio.on("user-join")
# async def user_join(sid, data):
#     log.info("user-join event received")
#     auth = data.get("auth")
#     if not auth or "token" not in auth or "client_id" not in auth:
#         return

#     data = await decode_token(auth["token"])
#     if data is None or "id" not in data:
#         return

#     user = Users.get_user_by_id(data["id"])
#     if not user:
#         return

#     if auth["client_id"] != str(user.id):
#         return

#     await add_session(sid, user.id)
#     await sio.enter_room(sid, user.id)

#     log.info(f"User {user.name}({user.id}) joined with session ID {sid}")

#     user_count = await get_user_count()
#     await sio.emit("user-count", {"count": user_count})
#     await sio.emit("usage", {"models": await get_models_in_use()})


# @sio.on("user-count")
# async def user_count(sid):
#     count = await get_user_count()
#     await sio.emit("user-count", {"count": count})


# @sio.on("usage")
# async def usage(sid, data):
#     model_id = data["model"]
#     key = f"USAGE_POOL:{model_id}:{sid}"

#     # Set the key with an expiration time
#     await USAGE_POOL.redis.set(key, 1, ex=TIMEOUT_DURATION)

#     # Broadcast the usage data to all clients
#     models_in_use = await get_models_in_use()
#     await sio.emit("usage", {"models": models_in_use})


# @sio.event
# async def disconnect(sid):
#     user_id = await SESSION_POOL.get(sid)
#     if user_id:
#         await remove_session(sid)
#         await sio.leave_room(sid, user_id)
#         log.info(f"User {user_id} disconnected with session ID {sid}")

#         # Update user count
#         user_count = await get_user_count()
#         await sio.emit("user-count", {"count": user_count})
#     else:
#         log.warning(f"Unknown session ID {sid} disconnected")


# # Event Emitter Functions


# def get_event_emitter(request_info):
#     async def __event_emitter__(event_data):
#         client_id = request_info.get("client_id")
#         if not client_id:
#             log.warning("No client_id in request_info")
#             return

#         await sio.emit(
#             "chat-events",
#             {
#                 "chat_id": request_info["chat_id"],
#                 "message_id": request_info["message_id"],
#                 "data": event_data,
#             },
#             room=client_id,
#         )

#     return __event_emitter__


# def get_event_call(request_info):
#     async def __event_call__(event_data):
#         client_id = request_info.get("client_id")
#         if not client_id:
#             log.warning("No client_id in request_info")
#             return None

#         response = await sio.call(
#             "chat-events",
#             {
#                 "chat_id": request_info["chat_id"],
#                 "message_id": request_info["message_id"],
#                 "data": event_data,
#             },
#             to=client_id,
#         )
#         return response

#     return __event_call__


async def shutdown():
    await SESSION_POOL.redis.close()
    await USER_POOL.redis.close()
    await USAGE_POOL.redis.close()

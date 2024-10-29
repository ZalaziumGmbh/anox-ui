import json
import redis.asyncio as redis


class AsyncRedisDict:
    def __init__(self, name, redis_url=None):
        self.name = name
        if redis_url:
            self.redis = redis.from_url(redis_url, decode_responses=True)
            self.use_redis = True
        else:
            self.store = {}
            self.use_redis = False

    async def __setitem__(self, key, value):
        if self.use_redis:
            serialized_value = json.dumps(value)
            await self.redis.hset(self.name, key, serialized_value)
        else:
            self.store[key] = value

    async def __getitem__(self, key):
        if self.use_redis:
            value = await self.redis.hget(self.name, key)
            if value is None:
                raise KeyError(key)
            return json.loads(value)
        else:
            if key in self.store:
                return self.store[key]
            else:
                raise KeyError(key)

    async def __delitem__(self, key):
        if self.use_redis:
            await self.redis.hdel(self.name, key)
        else:
            if key in self.store:
                del self.store[key]

    async def __contains__(self, key):
        if self.use_redis:
            return await self.redis.hexists(self.name, key)
        else:
            return key in self.store

    async def __len__(self):
        if self.use_redis:
            return await self.redis.hlen(self.name)
        else:
            return len(self.store)

    async def keys(self):
        if self.use_redis:
            return await self.redis.hkeys(self.name)
        else:
            return list(self.store.keys())

    async def values(self):
        if self.use_redis:
            values = await self.redis.hvals(self.name)
            return [json.loads(v) for v in values]
        else:
            return list(self.store.values())

    async def items(self):
        if self.use_redis:
            all_items = await self.redis.hgetall(self.name)
            return [(k, json.loads(v)) for k, v in all_items.items()]
        else:
            return list(self.store.items())

    async def get(self, key, default=None):
        try:
            return await self.__getitem__(key)
        except KeyError:
            return default

    async def clear(self):
        if self.use_redis:
            await self.redis.delete(self.name)
        else:
            self.store.clear()

    async def update(self, other=None, **kwargs):
        if other is not None:
            items = other.items() if hasattr(other, "items") else other
            for k, v in items:
                await self.__setitem__(k, v)
        for k, v in kwargs.items():
            await self.__setitem__(k, v)

    async def setdefault(self, key, default=None):
        if not await self.__contains__(key):
            await self.__setitem__(key, default)
        return await self.__getitem__(key)


# class AsyncRedisDict:
#     def __init__(self, name, redis_url):
#         self.name = name
#         self.redis = aioredis.from_url(redis_url, decode_responses=True)

#     async def __setitem__(self, key, value):
#         serialized_value = json.dumps(value)
#         await self.redis.hset(self.name, key, serialized_value)

#     async def __getitem__(self, key):
#         value = await self.redis.hget(self.name, key)
#         if value is None:
#             raise KeyError(key)
#         return json.loads(value)

#     async def __delitem__(self, key):
#         result = await self.redis.hdel(self.name, key)
#         if result == 0:
#             raise KeyError(key)

#     async def __contains__(self, key):
#         return await self.redis.hexists(self.name, key)

#     async def __len__(self):
#         return await self.redis.hlen(self.name)

#     async def keys(self):
#         return await self.redis.hkeys(self.name)

#     async def values(self):
#         values = await self.redis.hvals(self.name)
#         return [json.loads(v) for v in values]

#     async def items(self):
#         all_items = await self.redis.hgetall(self.name)
#         return [(k, json.loads(v)) for k, v in all_items.items()]

#     async def get(self, key, default=None):
#         try:
#             return await self.__getitem__(key)
#         except KeyError:
#             return default

#     async def clear(self):
#         await self.redis.delete(self.name)

#     async def update(self, other=None, **kwargs):
#         if other is not None:
#             items = other.items() if hasattr(other, "items") else other
#             for k, v in items:
#                 await self.__setitem__(k, v)
#         for k, v in kwargs.items():
#             await self.__setitem__(k, v)

#     async def setdefault(self, key, default=None):
#         if not await self.__contains__(key):
#             await self.__setitem__(key, default)
#         return await self.__getitem__(key)

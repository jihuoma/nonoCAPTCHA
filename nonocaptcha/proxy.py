import time
import asyncio

from peewee import SqliteDatabase, Model, CharField, BooleanField, IntegerField


database_filename = "proxy.db"
database = db = SqliteDatabase(
    database_filename, pragmas=(("synchronous", "off"),)
)


def init_db(dbname, remove=False):
    database.connect()
    database.create_tables([Proxy])
    Proxy.update(active=False).execute()


class Proxy(Model):
    class Meta:
        database = database

    proxy = CharField(primary_key=True)
    active = BooleanField(default=False)
    alive = BooleanField(default=False)
    last_used = IntegerField(default=0)
    last_banned = IntegerField(default=0)

    def __repr__(self):
        return (
            f"Proxy(ip={self.proxy}, active={self.active},",
            f"alive={self.alive}, last_used={self.last_used},",
            f"last_banned={self.last_banned})",
        )


# import os; if os.path.exists(database_filename): os.remove(database_filename)
init_db(database_filename)


class ProxyDB(object):
    _lock = asyncio.Lock()

    def __init__(self, last_banned_timeout=300):
        self.last_banned_timeout = last_banned_timeout

    def add(self, proxies):
        def chunks(l, n):
            n = max(1, n)
            return (l[i:i + n] for i in range(0, len(l), n))

        q = [proxy.proxy for proxy in Proxy.select(Proxy.proxy)]
        proxies_up = list(set(q) & set(proxies))
        proxies_dead = list(set(q) - set(proxies))
        proxies_new = set(proxies) - set(q)
        rows = [{"proxy": proxy, "alive": True} for proxy in proxies_new]

        with db.atomic():
            for dead in chunks(proxies_dead, 500):
                Proxy.update(alive=False).where(Proxy.proxy << dead).execute()

            for up in chunks(proxies_up, 500):
                Proxy.update(alive=True).where(Proxy.proxy << up).execute()

            for row in chunks(rows, 100):
                Proxy.insert_many(row).execute()

    async def get(self):
        try:
            async with self._lock:
                proxy = (
                    Proxy.select(Proxy.proxy)
                    .where(
                        (Proxy.active == 0)
                        & (Proxy.alive == 1)
                        & (
                            (
                                Proxy.last_banned + self.last_banned_timeout
                                <= time.time()
                            )
                            | (Proxy.last_banned == 0)
                        )
                    )
                    .order_by(Proxy.last_used)
                    .get()
                    .proxy
                )
                self.set_active(proxy, is_active=True)
        except Proxy.DoesNotExist:
            return
        return proxy

    def set_active(self, proxy, is_active):
        Proxy.update(active=is_active).where(Proxy.proxy == proxy).execute()
        if is_active:
            Proxy.update(last_used=time.time()).where(
                Proxy.proxy == proxy
            ).execute()

    def set_banned(self, proxy):
        query = Proxy.update(last_banned=time.time(), active=False).where(
            Proxy.proxy == proxy
        )
        return query.execute()

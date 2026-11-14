import unittest

import redis
from kombu.transport.redis import Channel


class RedisTransportCompatibilityTest(unittest.TestCase):
    def test_transport_accepts_installed_redis_client(self):
        """Проверка версии клиента должна проходить до подключения к брокеру."""
        channel = object.__new__(Channel)
        self.assertIs(channel._get_client(), redis.Redis)

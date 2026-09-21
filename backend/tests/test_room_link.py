"""Link de sala en la oferta de venta: python -m unittest discover -s tests -t ."""

import json
import unittest
from unittest import mock

import httpx

from app import room_link, sales


class MentionsOfferTests(unittest.TestCase):
    def test_reconoce_el_link_de_pago_y_el_de_la_sala(self):
        self.assertTrue(sales.mentions_offer("https://x.co/tiktok/T/checkout?productId=12&userTikTokId=3", 12))
        self.assertTrue(sales.mentions_offer("entra 👉 https://x.co/live/T/abc?p=12", 12))

    def test_12_no_coincide_con_123_ni_con_otros_parametros(self):
        self.assertFalse(sales.mentions_offer("https://x.co/live/T/abc?p=123", 12))
        self.assertFalse(sales.mentions_offer("https://x.co/checkout?productId=123&u=1", 12))
        self.assertFalse(sales.mentions_offer("hola, quiero el 12", 12))
        self.assertFalse(sales.mentions_offer("", 12))
        self.assertFalse(sales.mentions_offer(None, 12))


class CaptionTests(unittest.TestCase):
    def test_caption_de_sala_lleva_nombre_precio_y_link(self):
        text = sales.build_room_offer_caption("Maria", "Platera", 35000, "https://x.co/live/T/abc?p=1")
        self.assertIn("Hola Maria", text)
        self.assertIn("*Platera*", text)
        self.assertIn("$35.000", text)
        self.assertTrue(text.endswith("https://x.co/live/T/abc?p=1"))
        # el dedupe lo tiene que reconocer como oferta de ese producto
        self.assertTrue(sales.mentions_offer(text, 1))


def client_with(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


class FetchRoomLinkTests(unittest.TestCase):
    def setUp(self):
        patcher = mock.patch.multiple(
            room_link.settings,
            room_links_enabled=True,
            internal_api_key="clave-interna",
            liveshop_backend_url="http://backend:3000/",
        )
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_pide_el_link_con_la_clave_y_el_producto(self):
        seen = {}

        def handler(request: httpx.Request):
            seen["url"] = str(request.url)
            seen["key"] = request.headers.get("x-internal-key")
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"url": "https://liveshop.com.co/live/T/abc?p=7"})

        url = room_link.fetch_room_link(3, 7, client=client_with(handler))
        self.assertEqual(url, "https://liveshop.com.co/live/T/abc?p=7")
        self.assertEqual(seen["url"], "http://backend:3000/api/live-room/internal/link")
        self.assertEqual(seen["key"], "clave-interna")
        self.assertEqual(seen["body"], {"tiktokUserId": 3, "productId": 7})

    def test_apagado_no_llama_al_backend(self):
        def handler(request):
            raise AssertionError("no debia llamar al backend")

        with mock.patch.object(room_link.settings, "room_links_enabled", False):
            self.assertIsNone(room_link.fetch_room_link(3, 7, client=client_with(handler)))

    def test_sin_clave_no_llama_al_backend(self):
        def handler(request):
            raise AssertionError("no debia llamar al backend")

        with mock.patch.object(room_link.settings, "internal_api_key", ""):
            self.assertIsNone(room_link.fetch_room_link(3, 7, client=client_with(handler)))

    def test_si_el_backend_falla_devuelve_none_para_usar_el_link_de_pago(self):
        for response in (httpx.Response(500), httpx.Response(401), httpx.Response(404)):
            self.assertIsNone(room_link.fetch_room_link(3, 7, client=client_with(lambda r, resp=response: resp)))

    def test_si_no_hay_red_devuelve_none(self):
        def handler(request):
            raise httpx.ConnectError("sin red")

        self.assertIsNone(room_link.fetch_room_link(3, 7, client=client_with(handler)))

    def test_ignora_respuestas_raras(self):
        for body in ({"url": None}, {"url": "javascript:alert(1)"}, {}, {"url": 42}):
            self.assertIsNone(room_link.fetch_room_link(3, 7, client=client_with(lambda r, b=body: httpx.Response(200, json=b))))


if __name__ == "__main__":
    unittest.main()

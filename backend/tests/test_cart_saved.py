"""Aviso de pedido guardado al terminar el live: python -m unittest discover -s tests -t ."""

import unittest
from types import SimpleNamespace

from app.cart_saved import CartSavedDeps, build_message, deliver

URL = "https://liveshop.com.co/live/Mitienda/TOKEN123"
ITEMS = [{"name": "Platera", "quantity": 2}, {"name": "Camiseta", "quantity": 1}]


class BuildMessageTests(unittest.TestCase):
    def test_incluye_nombre_tienda_productos_y_link(self):
        text = build_message("Mitienda", "María", ITEMS, URL)
        self.assertIn("Hola María", text)
        self.assertIn("Terminó el live de Mitienda", text)
        self.assertIn("• 2 x Platera", text)
        self.assertIn("• 1 x Camiseta", text)
        self.assertIn("ya no está reservado", text)
        self.assertTrue(text.endswith(URL))

    def test_avisa_que_no_hay_reserva_sin_prometer_stock(self):
        text = build_message("Mitienda", None, ITEMS, URL)
        self.assertIn("si aún hay disponibilidad".lower(), text.lower())
        self.assertTrue(text.startswith("Hola "))

    def test_resume_cuando_son_muchos_productos(self):
        many = [{"name": f"P{i}", "quantity": 1} for i in range(8)]
        text = build_message("Mitienda", "Ana", many, URL)
        self.assertIn("• 1 x P4", text)
        self.assertNotIn("P5", text)
        self.assertIn("• y 3 más", text)


def make_deps(instance="tienda-wa", fail=False):
    sent = []

    def send_text(inst, phone, text):
        if fail:
            raise RuntimeError("whatsapp caido")
        sent.append((inst, phone, text))

    deps = CartSavedDeps(find_instance=lambda store: instance, send_text=send_text)
    return deps, sent


class DeliverTests(unittest.TestCase):
    def test_envia_al_numero_limpio_por_la_instancia_de_la_tienda(self):
        deps, sent = make_deps()
        out = deliver(deps, "Mitienda", "+57 300-123 4567", "María", URL, ITEMS)
        self.assertEqual(out, {"sent": True, "reason": None})
        self.assertEqual(sent[0][0], "tienda-wa")
        self.assertEqual(sent[0][1], "573001234567")
        self.assertIn(URL, sent[0][2])

    def test_telefono_invalido_no_envia(self):
        deps, sent = make_deps()
        for phone in ("", "abc", "123", "1" * 20, None):
            self.assertEqual(deliver(deps, "Mitienda", phone, None, URL, ITEMS)["reason"], "telefono_invalido", phone)
        self.assertEqual(sent, [])

    def test_solo_acepta_links_http(self):
        deps, sent = make_deps()
        for bad in ("javascript:alert(1)", "liveshop.com.co/live/x", ""):
            self.assertEqual(deliver(deps, "Mitienda", "3001234567", None, bad, ITEMS)["reason"], "link_invalido")
        self.assertEqual(sent, [])

    def test_tienda_sin_whatsapp(self):
        deps, sent = make_deps(instance=None)
        self.assertEqual(deliver(deps, "Mitienda", "3001234567", None, URL, ITEMS)["reason"], "tienda_sin_whatsapp")
        self.assertEqual(sent, [])

    def test_si_whatsapp_falla_no_revienta(self):
        deps, _ = make_deps(fail=True)
        with self.assertLogs("app.cart_saved", level="ERROR"):
            out = deliver(deps, "Mitienda", "3001234567", None, URL, ITEMS)
        self.assertEqual(out, {"sent": False, "reason": "error_whatsapp"})


if __name__ == "__main__":
    unittest.main()

"""Sala del live: python -m unittest discover -s tests -t .   (desde backend/)"""

import unittest
from types import SimpleNamespace

from app import room
from app.room_agent import RoomAgentDeps, answer

CATALOG = [
    {"id": 1, "name": "Platera de ceramica artesanal", "code": "AB12", "price": 35000,
     "stock": 8, "inStock": True, "description": "Hecha a mano"},
    {"id": 2, "name": "Camiseta oversize estampada", "code": "CD34", "price": 59900,
     "stock": 20, "inStock": True, "description": "Algodon premium"},
    {"id": 3, "name": "Vaso termico 500ml", "code": "EF56", "price": 42000,
     "stock": 0, "inStock": False, "description": ""},
]


class VisibilityTests(unittest.TestCase):
    def test_pregunta_de_producto_es_publica(self):
        for text in ("cuanto cuesta la platera?", "tienen la camiseta en negro", "envian a Medellin?"):
            self.assertEqual(room.classify_visibility(text), "public", text)

    def test_pedido_pago_y_datos_son_privados(self):
        for text in ("ya pagué, cuando llega mi pedido?", "quiero cambiar mi dirección",
                     "necesito la GUÍA de rastreo", "hice la transferencia", "quiero un reembolso"):
            self.assertEqual(room.classify_visibility(text), "private", text)

    def test_no_confunde_palabras_parecidas(self):
        # "pago" como palabra suelta es privado, pero "pagoda"/"apagon" no
        self.assertEqual(room.classify_visibility("tienen una pagoda decorativa?"), "public")


class SkipTests(unittest.TestCase):
    def test_saludos_y_risas_no_llaman_al_llm(self):
        for text in ("hola", "Hola!!", "jajaja", "gracias", "ok", "🔥🔥", "  "):
            self.assertTrue(room.should_skip(text), repr(text))

    def test_una_pregunta_si_se_responde(self):
        self.assertFalse(room.should_skip("cuanto cuesta la platera"))


class MatchProductsTests(unittest.TestCase):
    def test_por_codigo(self):
        self.assertEqual(room.match_products(CATALOG, "quiero el ab12")[0]["id"], 1)

    def test_por_nombre_con_plural_y_sin_tildes(self):
        found = room.match_products(CATALOG, "cuanto cuestan las plateras?")
        self.assertEqual([p["id"] for p in found], [1])

    def test_palabras_genericas_no_disparan_productos(self):
        self.assertEqual(room.match_products(CATALOG, "cuanto cuesta y tienen color?"), [])

    def test_el_codigo_gana_al_nombre(self):
        found = room.match_products(CATALOG, "la camiseta o el CD34")
        self.assertEqual(found[0]["id"], 2)
        self.assertEqual(len(found), 1)


class ParseReplyTests(unittest.TestCase):
    def test_no_responder(self):
        for raw in ("NO_RESPONDER", "no_responder", "NO RESPONDER", "", None, "   "):
            self.assertIsNone(room.parse_reply(raw), repr(raw))

    def test_quita_comillas(self):
        self.assertEqual(room.parse_reply('"Cuesta $35.000"'), "Cuesta $35.000")

    def test_recorta_respuestas_largas_en_una_palabra(self):
        out = room.parse_reply("palabra " * 100)
        self.assertLessEqual(len(out), room.MAX_REPLY_CHARS + 1)
        self.assertTrue(out.endswith("…"))


class ContextTests(unittest.TestCase):
    def test_incluye_precio_disponibilidad_y_variantes(self):
        text = room.build_context(
            "Mitienda", "Maria", "la camiseta en negro?", [CATALOG[1]],
            {2: [{"color": "Negro", "size": "M", "stock": 5}, {"color": "Blanco", "size": "L", "stock": 0}]},
            CATALOG, "public",
        )
        self.assertIn("$59.900", text)
        self.assertIn("Variante Negro / M: disponible", text)
        self.assertIn("Variante Blanco / L: agotada", text)
        self.assertIn("toda la sala", text)

    def test_privado_avisa_que_solo_lo_ve_el_cliente(self):
        text = room.build_context("Mitienda", None, "mi pedido", [], {}, CATALOG, "private")
        self.assertIn("solo este cliente", text)

    def test_el_prompt_incluye_el_de_la_tienda_y_las_reglas(self):
        prompt = room.build_system_prompt("Eres Sofi, vendedora.", "Mitienda")
        self.assertIn("Eres Sofi", prompt)
        self.assertIn(room.NO_REPLY_TOKEN, prompt)


def make_deps(reply="Cuesta $35.000 y está disponible.", store=True, api_key="k", llm_error=False):
    calls = SimpleNamespace(invoke=[], log=[])

    def invoke(cfg, system, human):
        calls.invoke.append((system, human))
        if llm_error:
            raise RuntimeError("proveedor caido")
        return reply, 120, 20

    deps = RoomAgentDeps(
        find_store=lambda name: {"id": 1, "name": "Mitienda"} if store else None,
        list_catalog=lambda store_id: CATALOG,
        list_variants=lambda ids: {},
        get_config=lambda store_id: SimpleNamespace(ai_api_key=api_key, system_prompt="Eres Sofi."),
        invoke=invoke,
        log=lambda *args: calls.log.append(args),
    )
    return deps, calls


class AgentFlowTests(unittest.TestCase):
    def test_responde_una_pregunta_de_producto_en_publico(self):
        deps, calls = make_deps()
        out = answer(deps, "Mitienda", "maria", "Maria", "cuanto cuesta la platera?")
        self.assertEqual(out, {"reply": "Cuesta $35.000 y está disponible.", "visibility": "public", "skipped": None})
        self.assertIn("Platera", calls.invoke[0][1])
        self.assertEqual(len(calls.log), 1)

    def test_pregunta_de_pedido_sale_privada(self):
        deps, _ = make_deps()
        out = answer(deps, "Mitienda", "maria", "Maria", "cuando llega mi pedido?")
        self.assertEqual(out["visibility"], "private")

    def test_un_saludo_no_gasta_llamada_de_ia(self):
        deps, calls = make_deps()
        out = answer(deps, "Mitienda", "maria", None, "hola")
        self.assertIsNone(out["reply"])
        self.assertEqual(calls.invoke, [])

    def test_el_agente_puede_decidir_no_responder(self):
        deps, _ = make_deps(reply="NO_RESPONDER")
        out = answer(deps, "Mitienda", "maria", None, "que lindo se ve todo")
        self.assertIsNone(out["reply"])
        self.assertEqual(out["skipped"], "sin_respuesta_necesaria")

    def test_tienda_sin_key_de_ia_no_responde(self):
        deps, calls = make_deps(api_key="")
        self.assertEqual(answer(deps, "Mitienda", "maria", None, "cuanto cuesta la platera")["skipped"], "sin_ia")
        self.assertEqual(calls.invoke, [])

    def test_tienda_desconocida(self):
        deps, _ = make_deps(store=False)
        self.assertEqual(answer(deps, "Otra", "maria", None, "cuanto cuesta la platera")["skipped"], "tienda_desconocida")

    def test_si_la_ia_falla_no_revienta_y_lo_registra(self):
        deps, calls = make_deps(llm_error=True)
        out = answer(deps, "Mitienda", "maria", None, "cuanto cuesta la platera")
        self.assertEqual((out["reply"], out["skipped"]), (None, "error_ia"))
        self.assertFalse(calls.log[0][4])  # success=False


if __name__ == "__main__":
    unittest.main()

"""Mensaje de retención por tienda: python -m unittest discover -s tests -t ."""

import unittest
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.db import Base
from app.models import StoreMessageTemplate
from app.routers import stores


class RetentionCopyTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine, tables=[StoreMessageTemplate.__table__])
        self.db = sessionmaker(bind=engine)()
        self.user = {"id": 1, "role": "user"}
        patcher = patch.object(stores, "require_store_access", lambda *_: None)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_sin_copia_propia_devuelve_el_por_defecto(self):
        res = stores.get_retention_copy(7, self.db, self.user)
        self.assertTrue(res["is_default"])
        self.assertEqual(res["text"], stores.DEFAULT_RETENTION_COPY)

    def test_guarda_actualiza_y_vuelve_al_por_defecto(self):
        body = stores.RetentionCopyIn(text="  Hola {nombre}, ¿cuál es tu @ de TikTok?  ")
        res = stores.save_retention_copy(7, body, self.db, self.user)
        self.assertEqual(res["text"], "Hola {nombre}, ¿cuál es tu @ de TikTok?")
        self.assertEqual(stores.get_retention_copy(7, self.db, self.user)["text"], res["text"])
        stores.save_retention_copy(7, stores.RetentionCopyIn(text="Otro"), self.db, self.user)
        self.assertEqual(stores.get_retention_copy(7, self.db, self.user)["text"], "Otro")
        # Otra tienda no se ve afectada
        self.assertTrue(stores.get_retention_copy(8, self.db, self.user)["is_default"])
        stores.save_retention_copy(7, stores.RetentionCopyIn(text=stores.DEFAULT_RETENTION_COPY), self.db, self.user)
        self.assertTrue(stores.get_retention_copy(7, self.db, self.user)["is_default"])

    def test_rechaza_vacio_y_muy_largo(self):
        for text in ("   ", "x" * (stores.RETENTION_COPY_MAX + 1)):
            with self.assertRaises(HTTPException):
                stores.save_retention_copy(7, stores.RetentionCopyIn(text=text), self.db, self.user)


class AskTextTests(unittest.TestCase):
    def setUp(self):
        engine = create_engine("sqlite://")
        Base.metadata.create_all(bind=engine, tables=[StoreMessageTemplate.__table__])
        self.db = sessionmaker(bind=engine)()

    def test_sin_mensaje_propio_usa_el_de_siempre(self):
        from app.whatsapp_link import ASK_TEXT, ask_text
        self.assertEqual(ask_text(self.db, 5, "Ana"), ASK_TEXT)

    def test_usa_el_de_la_tienda_con_y_sin_nombre(self):
        from app.whatsapp_link import ask_text
        self.db.add(StoreMessageTemplate(store_id=5, retention_copy="Hola {nombre}! ¿Tu @ de TikTok?"))
        self.db.commit()
        self.assertEqual(ask_text(self.db, 5, "Ana"), "Hola Ana! ¿Tu @ de TikTok?")
        self.assertEqual(ask_text(self.db, 5, None), "Hola! ¿Tu @ de TikTok?")
        self.assertEqual(ask_text(self.db, 5, "  "), "Hola! ¿Tu @ de TikTok?")


if __name__ == "__main__":
    unittest.main()

"""Prepare a known IMSS login state for the next queued request, without blind taps."""

import re
import sys


def prepare_login(app, path, instance, cancelled, wait):
    module = sys.modules[type(app).__module__]
    info = module.listar(path).get(instance)
    if not info or not info.get("android"):
        return False
    idx = info["index"]
    module.abrir_app(path, instance, idx)
    menu_opened = False
    logout_clicked = False
    confirmation_clicked = False
    for _ in range(20):
        if cancelled():
            return False
        nodes = [
            n
            for n in module.pantalla(path, idx)
            if n.get("visible", True) and n.get("area", 0) > 0
        ]
        text = module.texto_normalizado(module.todo_texto(nodes))
        fields = [n for n in nodes if n.get("enabled")]
        if module.buscar(fields, "txtCURP") and module.buscar(fields, "txtCorreo"):
            return True
        # An uncompleted validation belongs to a prior operation, not this queued CURP.
        if (
            module.cajas_codigo_validacion(nodes)
            or "codigo de validacion" in text
            or "error al validar" in text
        ):
            return False

        def exact(pattern):
            matches = [
                n
                for n in fields
                if any(
                    re.fullmatch(pattern, module.texto_normalizado(n.get(k, "")))
                    for k in ("valor", "descripcion", "texto")
                )
            ]
            return min(matches, key=lambda n: n["area"]) if matches else None

        target = None
        if module.tramite_confirmado(text):
            target = exact(r"aceptar|ok")
        elif (
            logout_clicked
            and not confirmation_clicked
            and re.search(r"(cerrar|cerrara).*sesion", text)
        ):
            target = exact(r"si|aceptar|cerrar sesion")
            if target:
                confirmation_clicked = True
        elif not logout_clicked:
            target = exact(r"cerrar sesion")
            if target:
                logout_clicked = True
            elif not menu_opened and re.search(
                r"tramita|vigencia|semanas cotizadas|mi perfil", text
            ):
                target = exact(
                    r"(?:abrir |open )?(?:menu|navigation drawer)|abrir menu de navegacion|open drawer|navigate up|abrir panel de navegacion"
                )
                if target:
                    menu_opened = True
        if target:
            module.tocar(path, idx, target["xy"])
        if wait(1):
            return False
    return False

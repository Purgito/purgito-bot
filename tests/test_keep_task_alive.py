"""keep_task_alive() (utils.py) retiene una referencia fuerte a una Task
fire-and-forget hasta que termina -- sin esto, asyncio solo guarda una
referencia débil a las Tasks en vuelo y el GC puede recolectarlas a mitad de
camino (ver la nota de la doc de asyncio.create_task), perdiendo el trabajo
sin ningún error visible. Este test verifica el contrato: la Task queda
pineada mientras corre y se libera sola al terminar."""

import asyncio

import utils


def test_keep_task_alive_pinea_y_libera_al_terminar():
    async def run():
        release = asyncio.Event()

        async def coro():
            await release.wait()

        task = utils.keep_task_alive(asyncio.create_task(coro()))
        assert task in utils._pinned_background_tasks

        release.set()
        await task

        assert task not in utils._pinned_background_tasks

    asyncio.run(run())


def test_keep_task_alive_devuelve_la_misma_task():
    async def run():
        async def coro():
            return "ok"

        original = asyncio.create_task(coro())
        returned = utils.keep_task_alive(original)
        assert returned is original
        assert await returned == "ok"

    asyncio.run(run())

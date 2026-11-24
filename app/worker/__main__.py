import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")

# Job claiming arrives in Stage 4; for now just stay alive.
while True:
    logging.info("worker idle")
    time.sleep(5)

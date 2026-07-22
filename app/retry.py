import time
from typing import Callable, Any

from app.logger import logger


def retry(
    func: Callable,
    *args,
    retries: int = 3,
    delay: int = 2,
    exceptions=(Exception,),
    **kwargs
) -> Any:
    """
    Execute a function with retry support.

    Parameters
    ----------
    func : function
        Function to execute.

    retries : int
        Number of attempts.

    delay : int
        Delay between attempts.

    exceptions : tuple
        Exception types to retry.

    Returns
    -------
    Any
        Function result.
    """

    last_exception = None

    for attempt in range(1, retries + 1):

        try:

            logger.info(
                "Attempt %s/%s : %s",
                attempt,
                retries,
                func.__name__,
            )

            return func(*args, **kwargs)

        except exceptions as e:

            last_exception = e

            logger.warning(
                "Attempt %s failed : %s",
                attempt,
                e,
            )

            if attempt < retries:

                logger.info(
                    "Retrying in %s second(s)...",
                    delay,
                )

                time.sleep(delay)

    logger.error(
        "%s failed after %s attempts",
        func.__name__,
        retries,
    )

    raise last_exception

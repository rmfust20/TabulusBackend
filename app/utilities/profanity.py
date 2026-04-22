from better_profanity import profanity

profanity.load_censor_words()


def contains_profanity(text: str) -> bool:
    if not text:
        return False
    return profanity.contains_profanity(text)

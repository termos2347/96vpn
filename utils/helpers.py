def generate_random_password(length=12):
    import random, string
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))
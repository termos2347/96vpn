# Заглушка для платёжного шлюза
class PaymentGateway:
    async def create_invoice(self, amount: int, currency: str, user_id: int) -> str:
        return "fake_invoice_link"
# راهنمای استفاده از WebSocket

این راهنما نحوه استفاده از WebSocket در این پروژه را برای ویژگی های زنده مانند چت و اعلان ها توضیح می دهد.

## اتصال به WebSocket

برای اتصال به WebSocket، باید از یک کتابخانه کلاینت WebSocket (به عنوان مثال، `socket.io-client` برای جاوا اسکریپت) استفاده کنید. URL WebSocket به صورت `ws://<your-domain>/ws/<endpoint>/` است.

### Endpoint ها

*   `/ws/chat/<conversation_id>/`: برای چت زنده در یک مکالمه.
*   `/ws/notifications/`: برای اعلان های زنده برای کاربر احراز هویت شده.

### احراز هویت

برای احراز هویت با WebSocket، باید توکن احراز هویت کاربر را در URL اتصال به عنوان یک پارامتر کوئری قرار دهید.

**مثال:**

```
ws://<your-domain>/ws/notifications/?token=<your-auth-token>
```

## WebSocket چت

### ارسال پیام

برای ارسال پیام در یک مکالمه، یک شی JSON با ساختار زیر را به WebSocket چت ارسال کنید:

```json
{
  "message": "Your message content"
}
```

**مثال با استفاده از `wscat`:**

```bash
wscat -c "ws://localhost:8000/ws/chat/1/?token=<your-auth-token>"
> {"message": "Hello, world!"}
```

### دریافت پیام

هنگامی که پیام جدیدی در مکالمه ارسال می شود، یک شی JSON با ساختار زیر از WebSocket چت دریافت خواهید کرد:

```json
{
  "id": 123,
  "sender": {
    "id": 1,
    "username": "testuser"
  },
  "content": "The message content",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

## WebSocket اعلان ها

### دریافت اعلان ها

هنگامی که اعلان جدیدی برای کاربر احراز هویت شده در دسترس باشد، یک شی JSON با ساختار زیر از WebSocket اعلان ها دریافت خواهید کرد:

```json
{
  "id": 1,
  "message": "The notification message",
  "is_read": false,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**مثال با استفاده از `wscat`:**

```bash
wscat -c "ws://localhost:8000/ws/notifications/?token=<your-auth-token>"
```

### علامت گذاری اعلان ها به عنوان خوانده شده

برای علامت گذاری یک اعلان به عنوان خوانده شده، باید یک درخواست به REST API ارسال کنید، نه از طریق WebSocket.

**مثال با استفاده از `curl`:**

```bash
curl -X POST -H "Authorization: Token <your-auth-token>" http://localhost:8000/api/notifications/1/read/
```

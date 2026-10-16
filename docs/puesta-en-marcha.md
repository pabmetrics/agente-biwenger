# Puesta en marcha: lo que hay que preparar a mano

Pasos que no puede hacer Claude Code porque necesitan tus cuentas. Van en orden de urgencia; cada uno dice qué desbloquea.

**Regla para todo:** los tokens y claves van en `.env` (local) o en el secret scope de Databricks. Nunca en el chat, en un commit ni en una captura.

## 1. Bot de Telegram · 5 min · desbloquea los avisos de error · ✅ hecho el 16/10/2026 (@pablo_biwenger_bot)

1. En Telegram, abre **@BotFather** y envía `/newbot`.
2. Elige un nombre (p. ej. "Agente Biwenger") y un usuario que acabe en `bot` (p. ej. `pablo_biwenger_bot`).
3. BotFather te da un token del tipo `123456789:AA...`. Pégalo en `.env` como `TELEGRAM_BOT_TOKEN=`.
4. Abre el chat con tu bot nuevo y envíale cualquier mensaje ("hola"). Sin esto, el bot no puede escribirte.
5. Avisa a Claude Code: saca tu `TELEGRAM_CHAT_ID` con una llamada a `getUpdates` y lo deja en `.env`.

## 2. Clave de la API de Claude · 5 min · desbloquea la Fase 4 · ✅ hecho el 16/10/2026

1. Entra en **console.anthropic.com** y añade un método de pago si no lo tienes.
2. **Settings → Limits**: pon un límite de gasto mensual bajo (p. ej. 10 $). El agente hará pocas llamadas al día.
3. **API Keys → Create Key**, con el nombre `agente-biwenger`.
4. Cópiala (solo se muestra una vez) en `.env` como `ANTHROPIC_API_KEY=`.

## 3. Databricks · 30–45 min · desbloquea el cierre de las Fases 1 y 2

### 3.1 Workspace y catálogo

1. Necesitas un workspace de **Azure Databricks con Unity Catalog** (los creados desde 2024 ya lo traen).
2. En el workspace, abre **SQL Editor** y ejecuta:

   ```sql
   CREATE CATALOG IF NOT EXISTS biwenger;
   CREATE SCHEMA IF NOT EXISTS biwenger.bronze;
   CREATE SCHEMA IF NOT EXISTS biwenger.silver;
   CREATE SCHEMA IF NOT EXISTS biwenger.gold;
   CREATE VOLUME IF NOT EXISTS biwenger.bronze.raw;
   ```

   Si `CREATE CATALOG` falla por permisos o por no tener ubicación de almacenamiento, usa el catálogo que ya tengas (p. ej. `main`) y díselo a Claude Code: solo cambia el prefijo.

### 3.2 CLI de Databricks en este portátil

Así Claude Code puede crear los secretos y el job desde aquí, sin que le pases ningún token.

```powershell
winget install Databricks.DatabricksCLI
databricks auth login --host https://<tu-workspace>.azuredatabricks.net
```

El login abre el navegador. Comprueba que funciona con `databricks current-user me`.

### 3.3 Secretos

Crea el scope y mete los secretos. Cada `put-secret` te pide el valor sin mostrarlo:

```powershell
databricks secrets create-scope biwenger
databricks secrets put-secret biwenger biwenger-token
databricks secrets put-secret biwenger biwenger-league-id
databricks secrets put-secret biwenger biwenger-user-id
databricks secrets put-secret biwenger telegram-bot-token
databricks secrets put-secret biwenger telegram-chat-id
```

Los valores son los mismos que tienes en `.env`.

### 3.4 Código en Databricks

1. Dile a Claude Code que haga **push** de `main` a GitHub (ahora mismo hay commits solo en local).
2. En Databricks: **User Settings → Linked accounts → GitHub**, y conecta tu cuenta.
3. **Workspace → Create → Git folder**, con la URL `https://github.com/pabmetrics/agente-biwenger`.

Con esto, Claude Code crea el job diario (ingesta → silver) con la CLI y lo prueba.

## 4. Decisiones pendientes del diseño · cuando quieras · las necesita la Fase 3

Respóndelas en el chat y quedarán en `docs/diseno-agente-biwenger.md`:

1. **Tope de compras por día:** ¿cuántas como máximo? ¿O un máximo de euros al día?
2. **Saldo negativo:** ¿se permite durante la semana (cuadrando antes de la jornada) o nunca? ¿Con qué tope en euros?
3. **Revalorización frente a puntos:** si un jugador está para venderse en 1–2 días, ¿se alinea igualmente si es de los que más puntos esperan?
4. **Precio al poner a la venta:** ¿siempre el valor de mercado o algo por encima? Recuerda que un mánager que pague ese precio se lo lleva sin que confirmes.

## 5. Endpoints de escritura · la próxima vez que operes en la web · los necesita la Fase 5

Cuando pujes, vendas, aceptes una oferta o cambies la alineación en **biwenger.as.com**:

1. Ten **F12 → Red** abierto, filtrando por `api/v2`.
2. Haz la acción y busca la petición que aparece (será `POST`, `PUT` o `DELETE`).
3. Apunta tres cosas: el **método**, la **URL** y la pestaña **Carga útil (Payload)**.
4. Pégaselas a Claude Code.

**No uses "Copiar como cURL"**: incluye tu token.

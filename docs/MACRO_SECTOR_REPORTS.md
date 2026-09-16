# Informes macro y sectoriales

El Investment Desk genera dos informes narrativos en español: uno diario después del snapshot de mercado y otro semanal los sábados. No son una tabla de scores ni un sistema de ejecución. Su objetivo es explicar el régimen macro, tasas, inflación, crecimiento, crédito, liquidez, amplitud y el estado de los once sectores GICS.

## Arquitectura

1. **Evidence Builder** carga los snapshots persistidos y congela un paquete de evidencia. Calcula agregados transparentes por sector: participación en tendencia, porcentaje sobre SMA200, fuerza relativa, líderes y variación frente al informe anterior.
2. **Market Strategist** convierte ese paquete en una narrativa desarrollada: resumen ejecutivo, cuatro bloques macro, escenarios base/alcista/bajista y dos párrafos por sector.
3. **Verifier** valida referencias, antigüedad del snapshot, cobertura macro y cantidad de sectores. Una referencia inexistente o menos de ocho sectores rechaza el informe. Datos viejos o cobertura macro reducida se muestran como limitación.
4. **Publisher** persiste el informe con una clave idempotente y lo divide en mensajes compatibles con Discord u otro webhook. Un informe rechazado no se envía.

El agente no descarga datos por su cuenta, no agrega causalidades externas y no tiene acceso a brokers, cuentas ni rutas de órdenes. Opera en `shadow_mode` y `no_execution`.

## Frecuencia y salida

- Diario: luego del snapshot, una vez por sesión de mercado.
- Semanal: sábado, una vez por semana ISO.
- UI: `Market > Market Reports`, con pestañas diaria y semanal y el paquete de evidencia desplegable.
- Entrega: webhook configurado en la aplicación o `ALERT_WEBHOOK_URL` para el usuario servidor.

Las claves `DATABASE_URL` y `DEV_USER_ID` permiten compartir el resultado entre GitHub Actions y Streamlit. Las ejecuciones programadas fallan de forma segura si no existe almacenamiento persistente.

## Criterio profesional

Los scores permanecen como insumos internos. La salida visible explica qué está pasando, por qué importa, qué confirmaría o invalidaría la lectura y qué riesgos vigilar. Los tickers líderes se citan como evidencia de participación, nunca como recomendación.

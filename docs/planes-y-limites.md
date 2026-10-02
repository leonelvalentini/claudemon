# Planes y límites

## Cómo funcionan los límites de Claude

Con los planes **Pro** y **Max**, el uso se mide en dos relojes:

1. **Ventana de 5 horas.** Arranca con tu primer mensaje y dura 5 h. Cuando se llena, esperás a que se reabra.
2. **Tope semanal.** Se reinicia siempre el mismo día y hora de tu cuenta. Hay uno para todos los modelos y otro solo para Sonnet.

Ese cupo **se comparte** entre Claude Code, claude.ai y la app.

Anthropic **no publica** cuántos tokens son el 100 %. Por eso `claudemon` no puede saberlo de antemano: lo aprende de vos.

## Configurarlo (una sola vez, 3 pasos)

```bash
claudemon plan max20            # tu plan: pro, max5 o max20
claudemon semana mar 09:00      # el día y la hora de reinicio: Ajustes → Uso en Claude
claudemon calibrar semana 48    # mirá /usage, y decile el % de la semana que ves
```

Con eso, `claudemon limites` calcula tu tope real (por regla de tres: si llevás 36 M tokens y `/usage` dice 48 %, el 100 % ≈ 75 M).

## Calibrar bien

- Calibrá cuando `/usage` muestre **20 % o más**. Con menos, el error es grande (el programa avisa).
- Podés calibrar varias veces: usa la **mediana**, así un dato raro no lo arruina.
- También se calibra la ventana de 5 h (`claudemon calibrar sesion 70`) y Sonnet (`claudemon calibrar sonnet 30`).
- Si cambia tu mezcla de modelos (de Sonnet a Opus, por ejemplo), **recalibrá**: Opus consume el cupo más rápido que Sonnet y `claudemon` cuenta tokens, no "peso".

## Cómo leer `claudemon limites`

```
Ventana de 5 horas:
  sin bloque activo: el próximo mensaje abre uno nuevo.

Semana (desde el reinicio: Tue 29/09 09:00):
  tokens nuevos 7.5M   Opus 7.5M · Sonnet 0 · otros 0
  faltan 3 d 22 h para el reinicio · ritmo 2.4M/día · al reinicio llegarías a 16.9M
  tope todos los modelos calibrado 90.0M: 8% ██░░░░░░░░░░░░░░░░░░; a este ritmo se agota en 34 d 2 h
```

- **ritmo:** lo que gastaste por día desde el último reinicio.
- **al reinicio llegarías a:** proyección si seguís igual.
- **se agota en:** si es **menos** que lo que falta para el reinicio, vas a quedarte sin cupo antes de que se renueve.

## Qué hacer si se va rápido

1. `claudemon sesiones` → mirá cuál es la sesión más cara.
2. `claudemon modelos` → ¿es Opus? ¿lo usan **subagentes**? Un subagente corre en el modelo que fija su definición (`.claude/agents/*.md`, campo `model:`), aunque tu conversación esté en Sonnet.
3. Las sesiones eternas (semanas abiertas) releen todo su contexto en cada turno: conviene cerrarlas y empezar una nueva (`/clear` o una sesión nueva).
4. Muchos agentes en paralelo multiplican el consumo.

# API HTTP del engine de Acestream

Resultado del spike del issue #3. Probado el 2026-10-07 contra Ace Stream Engine **3.1.74** (Windows) en `http://127.0.0.1:6878`, con los hashes de referencia de [idea.md](../idea.md).

Todo lo de este documento fue observado en un engine real, salvo lo marcado como **no verificado**.

## Resumen para el diseño

| Pregunta | Respuesta |
|----------|-----------|
| ¿Cómo sé si el engine está activo? | `GET /webui/api/service?method=get_version` devuelve la versión. |
| ¿Cómo valido un Content ID? | No se puede sin iniciar una sesión; hay que validar el formato (40 hex) en el cliente y luego pedir el stream. |
| ¿Cómo sé si un canal está vivo? | La sesión llega a `status = "dl"` con `downloaded > 0`. Los peers por sí solos no alcanzan. |
| ¿Hay seeds? | No. Solo existe `peers`. |
| ¿Cómo capturo una imagen? | `ffmpeg -i <playback_url> -frames:v 1` funciona (3 s, JPEG 1920x1080). |
| ¿Cómo libero la sesión? | `GET <command_url>?method=stop`. |
| ¿Cómo sé el nombre del canal? | `GET /server/api?api_version=3&method=get_media_files&content_id=<id>`, sin abrir sesión (spike de #50). |
| ¿Y su resolución? | Del tamaño del JPEG capturado; ffprobe da el mismo `width`/`height` (#49). |

## Endpoints

### Versión del engine

```
GET /webui/api/service?method=get_version
```

```json
{"result": {"code": 3017400, "platform": "win32", "version": "3.1.74"}, "error": null}
```

`/server/api?method=get_version` responde `{"result": null, "error": "access denied"}`; no usarlo.

### Iniciar una sesión de stream

```
GET /ace/getstream?id=<content_id>&format=json&pid=<uuid>
```

`pid` es un identificador de cliente; se envía un UUID nuevo por sesión. Sin parámetros devuelve HTTP 500.

Respuesta correcta (HTTP 200, en ~0,5 s):

```json
{
  "response": {
    "stat_url": "http://127.0.0.1:6878/ace/stat/<infohash>/<session>",
    "playback_url": "http://127.0.0.1:6878/ace/r/<infohash>/<session>",
    "command_url": "http://127.0.0.1:6878/ace/cmd/<infohash>/<session>",
    "playback_session_id": "...",
    "infohash": "<infohash>",
    "is_live": 1,
    "is_encrypted": 0,
    "client_session_id": -1
  },
  "error": null
}
```

**El Content ID no es el infohash.** De los 8 hashes de referencia, 7 devolvieron un `infohash` distinto del enviado. Hay que guardar siempre el Content ID que ingresó el usuario y no usar `infohash` como identidad del canal.

Contenido inexistente o mal formado (HTTP 200, en ~4 s):

```json
{"response": null, "error": "failed to load content"}
```

Tanto `0000...0000` como `not-a-hash` dieron este mismo error. El engine devuelve HTTP 200 también en los errores: hay que mirar el campo `error`.

**Enlaces con el infohash (#100).** Algunos enlaces `acestream://` traen el infohash del torrent en lugar del Content ID; tienen el mismo formato. Con `id=` el engine responde `failed to load content` a los ~4,6 s; con `getstream?infohash=<hash>` (y `get_media_files&infohash=<hash>`) carga en menos de un segundo. Un hash inexistente pedido con `infohash=` tarda ~28 s en dar el mismo error. Medido con el engine 3.1.74 y dos canales en vivo (ANTENA 3 Spain y AXN Movies Spain). Después de cargar un contenido por infohash, el engine lo acepta también con `id=` durante un tiempo (lo tiene en caché). El cliente prueba las dos formas: primero la que funcionó antes, si se sabe, y si no, como Content ID.

### Estadísticas de la sesión

```
GET <stat_url>
```

Evolución observada:

| `status` | Significado | Campos relevantes |
|----------|-------------|-------------------|
| `idle` | Sesión recién creada | Sin `peers` ni `downloaded` |
| `prebuf` | Buscando peers y llenando el buffer | `peers`, `downloaded`, `speed_down` |
| `dl` | Descargando; el stream es reproducible | Además trae `livepos` |

Campos útiles: `status`, `peers`, `speed_down` (unidad no verificada), `downloaded` (bytes), `is_live`, `infohash`.

Justo después de `getstream`, la primera consulta puede devolver `{"response": {}, "error": null}`, antes incluso de `idle` (observado al probar el cliente contra el engine real). Se interpreta como `idle`.

### Detener la sesión

```
GET <command_url>?method=stop
```

Devuelve `{"response": "ok", "error": null}`. Se hizo siempre al final de cada prueba.

### Reproducción

`playback_url` responde **HTTP 302** con `Location: http://127.0.0.1:6878/content/<infohash>/<token>`. El servidor es `BaseHTTP/0.3 Python/2.7.13`.

Al leer el cuerpo de la redirección con `httpx` la lectura quedó colgada hasta el timeout. No hace falta leerlo: para VLC y ffmpeg basta con pasar la `playback_url`, porque siguen la redirección.

### Nombre del contenido

Spike de #50, mismo engine 3.1.74:

```
GET /server/api?api_version=3&method=get_media_files&content_id=<content_id>
```

```json
{
  "result": {
    "files": [{"index": 0, "filename": "Sky Sports Main Event [UK]"}],
    "name": "Sky Sports Main Event [UK]",
    "infohash": "78266c15035d0ad8cbc58f821733931e1de434ab",
    "transport_type": "bt",
    "type": "live",
    "transport_file_cache_key": null
  }
}
```

- **No abre una sesión de stream** y no necesita token (con `token` de `get_api_access_token` responde igual).
- Funciona también con canales sin peers. Responde en milisegundos si el engine ya conoce el contenido.
- Contenido inexistente: `{"error": {"message": "cannot get transport file", "code": 0}}` tras ~4,7 s.
- `name` es el nombre con el que se publicó el contenido y puede traer propaganda, por ejemplo `"DAZN 1 1080 elcano.top https://x.com/... https://t.me/..."`. AceList quita las URLs.
- `get_content_info` no existe (`"unknown method"`). Ni `getstream` ni `stat` traen el nombre.

Alternativa observada, solo con el canal en `dl`: ffprobe sobre la `playback_url` muestra el `service_name` del flujo MPEG-TS (`"SKY SPORTS MAIN EVENT HD United Kingdom"`, o `"TNT Sports 1 HD United Kingdom"` para un contenido publicado como `"BT Sport 1 [UK]"`) y el tamaño del video (1920x1080). No se usa: exige el canal vivo y otro proceso, y `get_media_files` alcanza.

## Resultados con los hashes de referencia

Una sola ejecución de 20 s por hash; los peers cambian mucho entre ejecuciones.

| Content ID | Resultado | Peers | Notas |
|------------|-----------|-------|-------|
| `78266c15...` | `dl` en ~8 s | 3 a 5 | Único cuyo `infohash` coincide con el hash |
| `efc60cfe...` | `dl` en ~9 s | 1 | Vivo con un solo peer |
| `ecc85e5d...` | `prebuf` | 1 a 3 | Sin descarga tras 60 s |
| `f8b0eae8...` | `prebuf` | 0 a 9 | Llegó a 9 peers en una prueba y a 0 en otra; sin descarga en 60 s |
| `f16d68ff...`, `02be332e...`, `895d0863...` | `prebuf` | 0 a 3 | Sin descarga en 20 s |
| `dddff67e...` | `prebuf` | 0 | Sin peers |
| `0000...0000`, `not-a-hash` | `failed to load content` | n/a | Error tras ~4 s |

Conclusiones:

- Tener peers no implica que haya datos: varios hashes mostraron 1 a 9 peers sin descargar nada.
- Cuando un canal está vivo, llega a `dl` en unos 10 s o menos (observado en 2 de 8).

## Captura de pantalla

ffmpeg instalado en `C:\Program Files\ffmpeg\bin\ffmpeg.exe`. Con la sesión en `dl`:

```
ffmpeg -y -loglevel error -i <playback_url> -frames:v 1 -q:v 3 out.jpg
```

- Código de salida 0 en 3,2 s, JPEG de ~89 KB a 1920x1080 con imagen válida.
- ffmpeg emite avisos de h264 (`non-existing PPS 0 referenced`, `no frame!`) mientras espera el primer fotograma clave. No son un error: el código de salida y la existencia del archivo son la señal de éxito.

## Recomendaciones para el cliente (#7, #8, #9)

1. Validar `^[0-9a-fA-F]{40}$` antes de llamar al engine.
2. Detectar el engine con `get_version` antes de cualquier otra llamada y distinguir "engine caído" de "contenido inexistente".
3. Considerar un canal `alive` solo si la sesión llega a `dl` con `downloaded > 0` dentro de un timeout (propuesta inicial: 20 s, configurable). `no_peers` si termina el tiempo con `peers == 0`; si hay peers pero sin descarga, usar un estado intermedio o `no_peers` con el dato de peers guardado.
4. Mapear `error: "failed to load content"` a `not_found`.
5. Llamar siempre a `stop` en un `finally`, incluso ante errores o timeouts.
6. Capturar con ffmpeg sin shell (lista de argumentos) y solo cuando la sesión esté en `dl`.
7. No leer el cuerpo de `playback_url` con `httpx`.

## Notas de seguridad

El engine escucha en `0.0.0.0:6878`, es decir, es accesible desde la red local, no solo desde la propia PC. AceList debe seguir conectándose a `127.0.0.1` y no exponer su propia interfaz fuera de loopback.

## Pendiente

- **No verificado:** respuesta de `stat_url` después de `stop`.
- **No verificado:** comportamiento al arrancar la aplicación con el engine apagado (se probó solo con el engine encendido). Se cubre con tests en #7 y #21.
- **No verificado:** si los streams en `prebuf` llegan a `dl` con más de 60 s de espera.

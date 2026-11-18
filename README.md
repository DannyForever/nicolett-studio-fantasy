# nicolett-studio-fantasy
## 1. Descripción
### 1.1. ¿Qué hace?
El sistema centraliza y gestiona las entregas de proyectos académicos, permitiendo a los usuarios organizar archivos individuales y grupales, subir documentación de seguimiento y controlar las versiones del código en un solo entorno colaborativo.

### 1.2. ¿A quién va dirigido?
- Dueña  de _**Nicolett Studio Fantasy**_.
- Estilistas, manicuristas y profesionales de la estética que atienden con cita previa.
- Clientas del salón que buscan agendar servicios, ver catálogos y recibir recordatorios automáticos.

### 1.3. ¿Qué problema resuelve?
1. Elimina la _dispersión de archivos y carpetas locales_ desorganizadas entre los integrantes.
2. Evita los conflictos de versiones al unificar el código y las rúbricas en un _repositorio central_.
3. Reduce la fricción en la _colaboración grupal_ mediante una estructura clara y automatizada.

## 2. Tecnologías utilizadas
-  **Lenguaje:** Python
-  **Framework:** Django
-  **Base de datos:** SQLite por defecto; PostgreSQL puede configurarse mediante `DATABASE_URL`.

## 3. Instrucciones para ejecutar el proyecto localmente
### Con Docker
1. Instala y abre Docker Desktop.
2. Desde la carpeta raíz del repositorio, entra al proyecto Django:
   ```powershell
   cd "Fase 2\Evidencias Proyecto\Nicolett Studio Fantasy"
   ```
3. Si todavía no tienes un archivo `.env`, créalo desde el ejemplo:
   ```powershell
   Copy-Item .env.example .env
   ```
4. Construye la imagen e inicia la aplicación:
   ```powershell
   docker compose up --build
   ```
5. Abre http://localhost:8000. Para detenerla, presiona `Ctrl+C` y luego ejecuta:
   ```powershell
   docker compose down
   ```

Para que los comprobantes lleguen por correo, configura `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD` en `.env` con una cuenta SMTP y su contraseña de aplicación. Si se dejan vacíos, Django usa la consola local y no entrega correos. No compartas ni subas esas credenciales al repositorio.

Docker ejecuta las migraciones al iniciar y guarda la base de datos SQLite y los archivos subidos en volúmenes persistentes. Estos datos son independientes de la base de datos local y de la instancia desplegada en Render. No uses `docker compose down -v` si quieres conservarlos.

Para recibir actualizaciones de las imágenes versionadas, desde la raíz del repositorio ejecuta `git pull origin main` y luego, desde la carpeta del proyecto Django, reconstruye e inicia el contenedor:
```powershell
docker compose up --build -d
```
Al iniciar, Docker sobrescribe en el volumen persistente solo los PNG versionados de `media/servicios`; los demás archivos y la base de datos se conservan.

### Pagos con Transbank
Webpay Plus queda en modo de integración con `TRANSBANK_ENVIRONMENT=INTEGRATION` (valor predeterminado) y usa las credenciales de prueba del SDK oficial. Para producción, configura `TRANSBANK_ENVIRONMENT=PRODUCTION`, `TRANSBANK_COMMERCE_CODE`, `TRANSBANK_API_KEY` y una `TRANSBANK_RETURN_URL` pública con HTTPS en el archivo `.env` o en las variables seguras del despliegue. Nunca guardes credenciales reales en el repositorio ni las compartas por el chat. La aplicación registra la compra solo después de confirmar el pago con Transbank; si no puede completar una compra ya autorizada, intenta solicitar la devolución y conserva el estado para revisión si Transbank no la confirma. Antes de continuar a Webpay, el cliente puede volver al carrito; al regresar de Webpay, la aplicación verifica el estado de la transacción antes de permitir otro intento. Crédito, débito y prepago se eligen en la página segura de Webpay.

El checkout mantiene el carrito como paso de revisión y edición; al continuar, muestra un resumen separado antes de abrir Webpay. Cada token de Transbank se envía una sola vez desde un endpoint local que lo marca como abierto antes de transferirlo, para evitar el Error 21 al recargar o reintentar la misma sesión. Webpay abre en otra pestaña para conservar disponible la tienda; si presenta un error, el cliente vuelve a la pestaña de la tienda y usa la opción de volver al carrito, que verifica el estado antes de habilitar otro intento. Los datos de la tarjeta se ingresan únicamente en la página segura de Transbank.

### Sin Docker
Entra a `Fase 2\Evidencias Proyecto\Nicolett Studio Fantasy`, instala las dependencias de `requirements.txt` en un entorno virtual y ejecuta `python manage.py migrate` seguido de `python manage.py runserver`.

La configuración Docker descrita aquí es para desarrollo local; no modifica ni cambia el despliegue existente en Render.

## 4. Integrantes
- **Nicolett Studio Fantasy:** Product Owner
- **Daniela Huaiquiñir:** SCRUM Master y Equipo de desarrollo
- **Alejandra Garrido:** Equipo de desarrollo

## 5. Metodología de trabajo
* **Sprints:** Ciclos semanales de trabajo donde se planifican tareas específicas, se desarrollan funcionalidades y se realizan pruebas antes de la integración.
* **Gestión de tareas:** Por definir
* **Comunicación y revisiones:** Por definir

## 6. Arquitectura de la solución
Diseñado bajo un esquema cliente-servidor, utilizando una interfaz de usuario interactiva en el _frontend_ que se comunica de forma segura con una **API RESTful** en el _backend_.
- **Flujo de datos:**
  1. El usuario interactúa con la interfaz web enviando **peticiones HTTP**.
  2. El _backend_ procesa las solicitudes aplicando la lógica de negocio y gestiona las consultas a la base de datos.
  3. Los datos actualizados son devueltos al cliente en **formato JSON** para reflejar los cambios instantáneamente.
- **Diagrama:**

 > [!IMPORTANT]
> Este apartado será _actualizado_ para el desarrollo de la solución en la **Fase 2**.

import json
import tempfile
from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone
from PIL import Image

from .models import Categoria, Producto, Servicio
from usuarios.models import Rol, Usuario


class ServiciosPageTests(TestCase):
    def setUp(self):
        administrador = Usuario.objects.create_superuser(
            email='admin@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Admin',
            apellido_materno='Test',
            telefono='+56912345678',
        )
        self.client.force_login(administrador)
        self.media_dir = tempfile.TemporaryDirectory()
        self.media_override = override_settings(MEDIA_ROOT=self.media_dir.name)
        self.media_override.enable()
        self.categoria = Categoria.objects.create(nombre='Manicure', tipo='Uñas')

    def tearDown(self):
        self.media_override.disable()
        self.media_dir.cleanup()

    def imagen_png(self, nombre='servicio.png'):
        imagen = Image.new('RGB', (1, 1), color='white')
        contenido = BytesIO()
        imagen.save(contenido, format='PNG')
        return SimpleUploadedFile(nombre, contenido.getvalue(), content_type='image/png')

    def servicio_data(self, **overrides):
        data = {
            'nombre': 'Manicure clásica',
            'categoria': self.categoria.pk,
            'descripcion': 'Manicure tradicional',
            'precio': '12000',
            'duracion_minutos': '45',
            'activo': 'true',
        }
        data.update(overrides)
        return data

    def crear_servicio(self):
        return Servicio.objects.create(
            nombre='Manicure clásica',
            categoria=self.categoria,
            descripcion='Manicure tradicional',
            precio='12000',
            duracion_minutos=45,
            activo=True,
        )

    def test_servicios_page_renders_service_and_category_controls(self):
        self.crear_servicio()
        response = self.client.get(reverse('listar_servicios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'action="/panel_admin/categorias/crear/"')
        self.assertContains(response, 'Administrar categorías')
        self.assertContains(response, 'id="btnAdministrarCategoriasServicios"')
        self.assertContains(response, 'id="buscarCategoriaServicio"')
        self.assertContains(response, 'No hay categorías que coincidan con la búsqueda.')
        self.assertNotContains(response, 'class="category-manager"')
        self.assertNotContains(response, 'id="btnNuevaCategoria"')
        self.assertNotContains(response, '<th>Estado</th>')
        self.assertNotContains(response, 'data-bs-dismiss="modal">Cerrar')
        self.assertNotContains(response, 'Nueva categoría</h5>')
        self.assertContains(response, 'Disponibilidad para clientes')
        self.assertContains(response, 'data-live-filter="#serviciosTabla"')
        self.assertContains(response, 'data-filter-row')

    def test_create_service_persists_active_or_inactive_value(self):
        response = self.client.post(
            reverse('crear_servicio'),
            self.servicio_data(activo='false'),
        )

        self.assertRedirects(response, reverse('listar_servicios'))
        servicio = Servicio.objects.get(nombre='Manicure clásica')
        self.assertFalse(servicio.activo)
        self.assertEqual(servicio.categoria, self.categoria)
        self.assertEqual(str(servicio.precio), '12000.00')

    def test_edit_service_updates_fields_and_category_in_database(self):
        servicio = self.crear_servicio()
        otra_categoria = Categoria.objects.create(nombre='Pedicure', tipo='Pies')

        response = self.client.post(
            reverse('editar_servicio', args=[servicio.pk]),
            self.servicio_data(
                nombre='Pedicure spa',
                categoria=otra_categoria.pk,
                precio='18000',
                activo='false',
            ),
        )

        self.assertRedirects(response, reverse('listar_servicios'))
        servicio.refresh_from_db()
        self.assertEqual(servicio.nombre, 'Pedicure spa')
        self.assertEqual(servicio.categoria, otra_categoria)
        self.assertEqual(str(servicio.precio), '18000.00')
        self.assertFalse(servicio.activo)

    def test_service_can_be_activated_and_deactivated(self):
        servicio = self.crear_servicio()
        url = reverse('cambiar_estado_servicio', args=[servicio.pk])

        self.client.post(url)
        servicio.refresh_from_db()
        self.assertFalse(servicio.activo)

        self.client.post(url)
        servicio.refresh_from_db()
        self.assertTrue(servicio.activo)

    def test_delete_service_requires_post_and_removes_database_record(self):
        servicio = self.crear_servicio()
        url = reverse('eliminar_servicio', args=[servicio.pk])

        self.assertEqual(self.client.get(url).status_code, 405)
        response = self.client.post(url)

        self.assertRedirects(response, reverse('listar_servicios'))
        self.assertFalse(Servicio.objects.filter(pk=servicio.pk).exists())

    def test_delete_service_also_removes_its_image_from_media_storage(self):
        response = self.client.post(
            reverse('crear_servicio'),
            {**self.servicio_data(), 'imagen_url': self.imagen_png()},
        )
        self.assertRedirects(response, reverse('listar_servicios'))
        servicio = Servicio.objects.get(nombre='Manicure clásica')
        self.assertTrue(servicio.imagen_url.storage.exists(servicio.imagen_url.name))

        self.client.post(reverse('eliminar_servicio', args=[servicio.pk]))

        self.assertFalse(Servicio.objects.filter(pk=servicio.pk).exists())
        self.assertFalse(servicio.imagen_url.storage.exists(servicio.imagen_url.name))

    def test_replacing_service_image_removes_the_old_file(self):
        servicio = self.crear_servicio()
        servicio.imagen_url = self.imagen_png('anterior.png')
        servicio.save()
        imagen_anterior = servicio.imagen_url.name
        storage = servicio.imagen_url.storage
        self.assertTrue(storage.exists(imagen_anterior))

        response = self.client.post(
            reverse('editar_servicio', args=[servicio.pk]),
            {**self.servicio_data(), 'imagen_url': self.imagen_png('nueva.png')},
        )

        self.assertRedirects(response, reverse('listar_servicios'))
        servicio.refresh_from_db()
        self.assertNotEqual(servicio.imagen_url.name, imagen_anterior)
        self.assertFalse(storage.exists(imagen_anterior))
        self.assertTrue(servicio.imagen_url.storage.exists(servicio.imagen_url.name))

    def test_edit_modal_shows_existing_image_preview_and_remove_option(self):
        servicio = self.crear_servicio()
        servicio.imagen_url = self.imagen_png('manicure.png')
        servicio.save()

        response = self.client.get(reverse('listar_servicios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, servicio.imagen_url.url)
        self.assertContains(response, 'data-imagen-nombre="servicios/manicure.png"')
        self.assertContains(response, 'name="imagen_url-clear"')
        self.assertContains(response, 'Quitar imagen actual')

    def test_edit_service_can_remove_existing_image(self):
        servicio = self.crear_servicio()
        servicio.imagen_url = self.imagen_png('quitar.png')
        servicio.save()
        image_name = servicio.imagen_url.name
        storage = servicio.imagen_url.storage

        response = self.client.post(
            reverse('editar_servicio', args=[servicio.pk]),
            {**self.servicio_data(), 'imagen_url-clear': 'on'},
        )

        self.assertRedirects(response, reverse('listar_servicios'))
        servicio.refresh_from_db()
        self.assertFalse(servicio.imagen_url)
        self.assertFalse(storage.exists(image_name))

    def test_deleting_service_preserves_image_still_used_by_another_service(self):
        servicio = self.crear_servicio()
        servicio.imagen_url = self.imagen_png()
        servicio.save()
        imagen_compartida = servicio.imagen_url.name
        otro_servicio = Servicio.objects.create(
            nombre='Manicure francesa',
            categoria=self.categoria,
            descripcion='',
            precio='15000',
            duracion_minutos=50,
            activo=True,
            imagen_url=imagen_compartida,
        )

        self.client.post(reverse('eliminar_servicio', args=[servicio.pk]))

        self.assertFalse(Servicio.objects.filter(pk=servicio.pk).exists())
        self.assertTrue(Servicio.objects.filter(pk=otro_servicio.pk).exists())
        self.assertTrue(otro_servicio.imagen_url.storage.exists(imagen_compartida))

    def producto_data(self, **overrides):
        data = {
            'nombre': 'Aceite nutritivo',
            'categoria': self.categoria.pk,
            'descripcion': 'Cuidado en casa para mantener el tratamiento.',
            'precio': '9900',
            'stock': '12',
            'activo': 'true',
        }
        data.update(overrides)
        return data

    def crear_producto(self, **overrides):
        data = self.producto_data(**overrides)
        return Producto.objects.create(
            nombre=data['nombre'],
            categoria=self.categoria,
            descripcion=data['descripcion'],
            precio=data['precio'],
            stock=data['stock'],
            activo=data['activo'] == 'true',
        )

    def test_product_page_lists_products_and_category_choices(self):
        self.crear_producto()

        response = self.client.get(reverse('admin_productos'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Productos Activos')
        self.assertContains(response, 'Productos Inactivos')
        self.assertContains(response, 'Aceite nutritivo')
        self.assertContains(response, 'Cuidado en casa')
        self.assertContains(response, 'Manicure (Uñas)')
        self.assertContains(response, 'id="buscarCategoriaProducto"')
        self.assertNotContains(response, 'listaCategoriasInlineProducto')
        self.assertNotContains(response, 'data-add-product-category')
        self.assertContains(response, 'data-live-filter="#productosTabla"')
        self.assertContains(response, 'data-filter-row')

    def test_admin_dashboard_uses_compact_sentence_case_appointment_headers(self):
        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'dashboard-appointments-table')
        self.assertContains(response, reverse('admin_recordatorios'))
        self.assertNotContains(response, 'Fichas de clientas')
        for heading in ('Fecha', 'Hora', 'Cliente', 'Servicio', 'Profesional', 'Acompañante', 'Estado'):
            self.assertContains(response, f'<th>{heading}</th>', html=True)
        self.assertNotContains(response, '<th>HORA</th>', html=True)

    def test_admin_dashboard_lists_upcoming_client_appointments_and_companion_status(self):
        from agenda.models import Reserva

        hoy = timezone.localdate()
        reserva_con_acompanante = Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(hoy + timedelta(days=5), datetime.min.time())),
            estado='confirmada',
            cliente_nombre='Camila Pérez',
            servicio_nombre='Manicure',
            viene_con_acompanante=True,
        )
        Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(hoy + timedelta(days=2), datetime.min.time())),
            estado='confirmada',
            cliente_nombre='Sofía López',
            servicio_nombre='Pedicure',
            viene_con_acompanante=False,
        )
        Reserva.objects.create(
            fecha_hora=timezone.make_aware(datetime.combine(hoy + timedelta(days=1), datetime.min.time())),
            estado='cancelada',
            cliente_nombre='Reserva cancelada',
            servicio_nombre='Manicure',
        )

        response = self.client.get(reverse('admin_dashboard'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Próximas citas')
        self.assertContains(response, 'Camila Pérez')
        self.assertContains(response, 'Sofía López')
        self.assertContains(response, reserva_con_acompanante.fecha_hora.strftime('%d/%m/%Y'))
        self.assertContains(response, 'Sí')
        self.assertContains(response, 'No')
        self.assertNotContains(response, 'Reserva cancelada')
        self.assertEqual(
            [reserva.cliente_nombre for reserva in response.context['proximas_citas']],
            ['Sofía López', 'Camila Pérez'],
        )

    def test_create_product_saves_all_fields_to_database(self):
        response = self.client.post(
            reverse('crear_producto'),
            {**self.producto_data(stock='7', activo='false'), 'imagen_url': self.imagen_png('aceite.png')},
        )

        self.assertRedirects(response, reverse('admin_productos'))
        producto = Producto.objects.get(nombre='Aceite nutritivo')
        self.assertEqual(producto.categoria, self.categoria)
        self.assertEqual(str(producto.precio), '9900.00')
        self.assertEqual(producto.stock, 7)
        self.assertFalse(producto.activo)
        self.assertTrue(producto.imagen_url.storage.exists(producto.imagen_url.name))

    def test_create_product_requires_an_image(self):
        response = self.client.post(
            reverse('crear_producto'),
            self.producto_data(),
            follow=True,
        )

        self.assertFalse(Producto.objects.exists())
        self.assertContains(response, 'Este campo es obligatorio.')

    def test_edit_product_updates_stock_price_category_and_status(self):
        producto = self.crear_producto()
        otra_categoria = Categoria.objects.create(nombre='Cabello', tipo='Tratamientos')

        response = self.client.post(
            reverse('editar_producto', args=[producto.pk]),
            self.producto_data(
                nombre='Mascarilla capilar',
                categoria=otra_categoria.pk,
                precio='15990',
                stock='4',
                activo='false',
            ),
        )

        self.assertRedirects(response, reverse('admin_productos'))
        producto.refresh_from_db()
        self.assertEqual(producto.nombre, 'Mascarilla capilar')
        self.assertEqual(producto.categoria, otra_categoria)
        self.assertEqual(str(producto.precio), '15990.00')
        self.assertEqual(producto.stock, 4)
        self.assertFalse(producto.activo)

    def test_edit_product_preserves_existing_image_when_no_replacement_is_selected(self):
        producto = self.crear_producto()
        producto.imagen_url = self.imagen_png('original.png')
        producto.save()
        original_image = producto.imagen_url.name
        storage = producto.imagen_url.storage

        response = self.client.post(
            reverse('editar_producto', args=[producto.pk]),
            self.producto_data(nombre='Aceite editado'),
        )

        self.assertRedirects(response, reverse('admin_productos'))
        producto.refresh_from_db()
        self.assertEqual(producto.imagen_url.name, original_image)
        self.assertTrue(storage.exists(original_image))

    def test_edit_product_can_replace_but_not_clear_existing_image(self):
        producto = self.crear_producto()
        producto.imagen_url = self.imagen_png('anterior.png')
        producto.save()
        image_anterior = producto.imagen_url.name
        storage = producto.imagen_url.storage

        response = self.client.post(
            reverse('editar_producto', args=[producto.pk]),
            {
                **self.producto_data(nombre='Producto actualizado'),
                'imagen_url-clear': 'on',
                'imagen_url': self.imagen_png('reemplazo.png'),
            },
        )

        self.assertRedirects(response, reverse('admin_productos'))
        producto.refresh_from_db()
        self.assertNotEqual(producto.imagen_url.name, image_anterior)
        self.assertTrue(storage.exists(producto.imagen_url.name))
        self.assertFalse(storage.exists(image_anterior))

    def test_edit_product_ignores_clear_request_without_replacement(self):
        producto = self.crear_producto()
        producto.imagen_url = self.imagen_png('conservar.png')
        producto.save()
        image_name = producto.imagen_url.name
        storage = producto.imagen_url.storage

        self.client.post(
            reverse('editar_producto', args=[producto.pk]),
            {**self.producto_data(), 'imagen_url-clear': 'on'},
        )

        producto.refresh_from_db()
        self.assertEqual(producto.imagen_url.name, image_name)
        self.assertTrue(storage.exists(image_name))

    def test_product_form_marks_image_required_only_for_new_products(self):
        response = self.client.get(reverse('admin_productos'))

        self.assertContains(response, 'id="productoImagen" type="file" name="imagen_url" class="form-control salon-file-input" accept="image/*"')
        self.assertContains(response, 'La imagen es obligatoria al registrar el producto.')
        self.assertNotContains(response, 'Quitar imagen actual')


    def test_product_stock_cannot_be_negative(self):
        response = self.client.post(
            reverse('crear_producto'),
            self.producto_data(stock='-1'),
            follow=True,
        )

        self.assertFalse(Producto.objects.exists())
        self.assertContains(response, 'El stock no puede ser negativo.')

    def test_product_can_be_activated_and_deactivated(self):
        producto = self.crear_producto()
        url = reverse('cambiar_estado_producto', args=[producto.pk])

        self.client.post(url)
        producto.refresh_from_db()
        self.assertFalse(producto.activo)

        self.client.post(url)
        producto.refresh_from_db()
        self.assertTrue(producto.activo)

    def test_delete_product_removes_database_record_and_image(self):
        producto = self.crear_producto()
        producto.imagen_url = self.imagen_png('producto.png')
        producto.save()
        image_name = producto.imagen_url.name
        storage = producto.imagen_url.storage

        self.client.post(reverse('eliminar_producto', args=[producto.pk]))

        self.assertFalse(Producto.objects.filter(pk=producto.pk).exists())
        self.assertFalse(storage.exists(image_name))

    def test_category_can_be_created_and_selected_through_modal_endpoint(self):
        response = self.client.post(
            reverse('crear_categoria'),
            {'nombre': 'Coloración', 'tipo': 'Cabello'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        data = json.loads(response.content)
        self.assertEqual(data['nombre'], 'Coloración')
        self.assertTrue(Categoria.objects.filter(pk=data['id'], tipo='Cabello').exists())

    def test_category_can_be_edited_from_service_modal(self):
        self.categoria.activa = False
        self.categoria.save(update_fields=['activa'])

        response = self.client.post(
            reverse('editar_categoria', args=[self.categoria.pk]),
            {'nombre': 'Manicure premium', 'tipo': 'Uñas'},
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.categoria.refresh_from_db()
        self.assertEqual(self.categoria.nombre, 'Manicure premium')
        self.assertTrue(self.categoria.activa)

    def test_category_with_services_cannot_be_deleted(self):
        servicio = self.crear_servicio()

        response = self.client.post(
            reverse('eliminar_categoria', args=[self.categoria.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Categoria.objects.filter(pk=self.categoria.pk).exists())
        self.assertTrue(Servicio.objects.filter(pk=servicio.pk).exists())

    def test_category_with_products_cannot_be_deleted(self):
        producto = self.crear_producto()

        response = self.client.post(
            reverse('eliminar_categoria', args=[self.categoria.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 409)
        self.assertTrue(Categoria.objects.filter(pk=self.categoria.pk).exists())
        self.assertTrue(Producto.objects.filter(pk=producto.pk).exists())

    def test_unused_category_can_be_deleted(self):
        response = self.client.post(
            reverse('eliminar_categoria', args=[self.categoria.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Categoria.objects.filter(pk=self.categoria.pk).exists())


class PersonalTests(TestCase):
    def setUp(self):
        Rol.objects.create(id=1, nombre='Admin')
        Rol.objects.create(id=4, nombre='Cliente')
        administrador = Usuario.objects.create_superuser(
            email='admin@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Admin',
            apellido_materno='Test',
            telefono='+56912345678',
        )
        self.client.force_login(administrador)
        self.rol_colaborador = Rol.objects.create(id=5, nombre='Colaborador')
        self.categoria_unas = Categoria.objects.create(nombre='Uñas', tipo='Manicure y pedicure')
        self.categoria_cabello = Categoria.objects.create(nombre='Cabello', tipo='Peluquería')

    def datos_personal(self, **overrides):
        data = {
            'nombre': 'Juan',
            'segundo_nombre': '',
            'apellido_paterno': 'Pérez',
            'apellido_materno': 'Soto',
            'telefono': '+56912345678',
            'email': 'juan.perez@example.com',
        }
        data.update(overrides)
        return data

    def crear_personal(self, **overrides):
        usuario = Usuario(**self.datos_personal(**overrides), rol=self.rol_colaborador)
        usuario.set_unusable_password()
        usuario.save()
        return usuario

    def test_personnel_page_lists_only_collaborators_and_new_staff_button(self):
        colaborador = self.crear_personal()
        Usuario.objects.create(
            nombre='Cliente',
            segundo_nombre='',
            apellido_paterno='Prueba',
            apellido_materno='Prueba',
            telefono='123',
            email='cliente@example.com',
            rol=Rol.objects.get(nombre='Cliente'),
            password='hash',
        )

        response = self.client.get(reverse('admin_personal'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Añadir personal')
        self.assertContains(response, 'juan.perez@example.com')
        self.assertNotContains(response, 'cliente@example.com')
        self.assertContains(response, 'Colaborador')
        self.assertContains(response, 'data-live-filter="#personalTabla"')
        self.assertContains(response, 'data-filter-row')
        self.assertTrue(Usuario.objects.filter(pk=colaborador.pk, rol_id=5).exists())

    def test_deleting_unused_specialty_category_unlinks_it_from_collaborators(self):
        from agenda.models import ProfesionalCategoria

        colaborador = self.crear_personal()
        ProfesionalCategoria.objects.create(
            profesional=colaborador,
            categoria_id=self.categoria_unas.pk,
        )

        response = self.client.post(
            reverse('eliminar_categoria', args=[self.categoria_unas.pk]),
            HTTP_X_REQUESTED_WITH='XMLHttpRequest',
        )

        self.assertEqual(response.status_code, 200)
        self.assertFalse(Categoria.objects.filter(pk=self.categoria_unas.pk).exists())
        self.assertFalse(
            ProfesionalCategoria.objects.filter(
                profesional=colaborador,
                categoria_id=self.categoria_unas.pk,
            ).exists(),
        )
        self.assertTrue(Usuario.objects.filter(pk=colaborador.pk).exists())

    def test_create_personnel_sets_collaborator_role_and_no_login_password(self):
        response = self.client.post(
            reverse('crear_personal'),
            {
                **self.datos_personal(),
                'especializaciones': [str(self.categoria_unas.pk)],
            },
        )

        self.assertRedirects(response, reverse('admin_personal'))
        usuario = Usuario.objects.get(email='juan.perez@example.com')
        self.assertEqual(usuario.rol_id, 5)
        self.assertTrue(usuario.is_active)
        self.assertTrue(usuario.is_staff)
        self.assertIsNotNone(usuario.acepta_terminos_at)
        self.assertFalse(usuario.is_superuser)
        self.assertFalse(usuario.has_usable_password())
        self.assertEqual(
            list(usuario.especialidades.values_list('categoria__nombre', flat=True)),
            ['Uñas'],
        )

        cliente_login = Client()
        login_response = cliente_login.post(
            reverse('login'),
            {'email': usuario.email, 'password': 'cualquier-clave'},
        )
        self.assertNotEqual(login_response.status_code, 302)
        self.assertNotIn('_auth_user_id', cliente_login.session)

    def test_create_personnel_rejects_duplicate_email(self):
        self.crear_personal()

        response = self.client.post(
            reverse('crear_personal'),
            {
                **self.datos_personal(nombre='Otro'),
                'especializaciones': [str(self.categoria_unas.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['personal_form'].errors['email'])
        self.assertEqual(Usuario.objects.filter(email='juan.perez@example.com').count(), 1)

    def test_create_personnel_requires_specialization_and_keeps_form_errors_visible(self):
        response = self.client.post(
            reverse('crear_personal'),
            self.datos_personal(),
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'data-server-errors="true"')
        self.assertTrue(response.context['personal_form'].errors['especializaciones'])
        self.assertFalse(Usuario.objects.filter(email='juan.perez@example.com').exists())

    def test_specialization_choices_list_categories_registered_in_database(self):
        from panel_admin.forms import PersonalForm

        categoria_pestanas = Categoria.objects.create(nombre='Pestañas', tipo='Mirada')
        form = PersonalForm()

        response = self.client.get(reverse('admin_personal'))

        self.assertEqual(form.fields['especializaciones'].help_text, '')
        self.assertIsNone(form.fields['telefono'].widget.attrs.get('placeholder'))
        self.assertContains(response, 'class="specialization-list"')
        self.assertContains(response, f'value="{self.categoria_unas.pk}"')
        self.assertContains(response, f'value="{self.categoria_cabello.pk}"')
        self.assertContains(response, f'value="{categoria_pestanas.pk}"')
        self.assertContains(response, 'Uñas')
        self.assertContains(response, 'Cabello')
        self.assertContains(response, 'Pestañas')
        self.assertNotContains(response, 'Selecciona todas las áreas')

    def test_create_personnel_saves_multiple_specializations(self):
        response = self.client.post(
            reverse('crear_personal'),
            {
                **self.datos_personal(),
                'especializaciones': [
                    str(self.categoria_unas.pk),
                    str(self.categoria_cabello.pk),
                ],
            },
        )

        self.assertRedirects(response, reverse('admin_personal'))
        usuario = Usuario.objects.get(email='juan.perez@example.com')
        self.assertEqual(
            set(usuario.especialidades.values_list('categoria_id', flat=True)),
            {self.categoria_unas.pk, self.categoria_cabello.pk},
        )

    def test_create_personnel_normalizes_supported_chilean_mobile_formats(self):
        from panel_admin.forms import PersonalForm

        for telefono in ('+56 9 1234 5678', '9 1234 5678', '912345678'):
            with self.subTest(telefono=telefono):
                form = PersonalForm(data={
                    **self.datos_personal(telefono=telefono),
                    'especializaciones': [str(self.categoria_unas.pk)],
                })

                self.assertTrue(form.is_valid(), form.errors)
                self.assertEqual(form.cleaned_data['telefono'], '+56912345678')

    def test_create_personnel_rejects_invalid_chilean_mobile_formats(self):
        from panel_admin.forms import PersonalForm

        for telefono in ('123', '91234567', '9123456780', '+56 2 2345 6789', '+57 9 1234 5678'):
            with self.subTest(telefono=telefono):
                form = PersonalForm(data={
                    **self.datos_personal(telefono=telefono),
                    'especializaciones': [str(self.categoria_unas.pk)],
                })

                self.assertFalse(form.is_valid())
                self.assertIn('telefono', form.errors)
                self.assertIn(
                    'Formato requerido: +569 XXXX XXXX o 9 XXXX XXXX.',
                    form.errors['telefono'],
                )

    def test_create_personnel_rejects_invalid_email(self):
        response = self.client.post(
            reverse('crear_personal'),
            {
                **self.datos_personal(email='correo-invalido'),
                'especializaciones': [str(self.categoria_unas.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Introduzca una dirección de correo electrónico válida.')
        self.assertFalse(Usuario.objects.filter(email='correo-invalido').exists())

    def test_invalid_personnel_edit_renders_errors_with_edit_action(self):
        usuario = self.crear_personal()
        response = self.client.post(
            reverse('editar_personal', args=[usuario.pk]),
            {
                **self.datos_personal(telefono='123'),
                'especializaciones': [str(self.categoria_unas.pk)],
            },
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context['personal_form'].errors['telefono'])
        create_url = reverse('crear_personal')
        self.assertEqual(
            response.context['form_action'],
            reverse('editar_personal', args=[usuario.pk]),
        )
        self.assertTrue(response.context['form_is_edit'])
        self.assertContains(response, f'data-create-url="{create_url}"')

    def test_edit_personnel_updates_contact_details_without_changing_role(self):
        usuario = self.crear_personal()
        from agenda.models import ProfesionalCategoria
        ProfesionalCategoria.objects.create(
            profesional=usuario,
            categoria_id=self.categoria_unas.pk,
        )

        response = self.client.post(
            reverse('editar_personal', args=[usuario.pk]),
            {
                **self.datos_personal(telefono='+56987654321', email='nuevo@example.com'),
                'especializaciones': [str(self.categoria_cabello.pk)],
            },
        )

        self.assertRedirects(response, reverse('admin_personal'))
        usuario.refresh_from_db()
        self.assertEqual(usuario.telefono, '+56987654321')
        self.assertEqual(usuario.email, 'nuevo@example.com')
        self.assertEqual(usuario.rol_id, 5)
        self.assertEqual(
            list(usuario.especialidades.values_list('categoria__nombre', flat=True)),
            ['Cabello'],
        )

    def test_personnel_list_shows_specialties_and_edit_modal_preselects_them(self):
        usuario = self.crear_personal()
        from agenda.models import ProfesionalCategoria
        ProfesionalCategoria.objects.create(
            profesional=usuario,
            categoria_id=self.categoria_unas.pk,
        )

        response = self.client.get(reverse('admin_personal'))

        self.assertContains(response, 'ESPECIALIZACIÓN')
        self.assertContains(response, 'Uñas')
        self.assertContains(response, f'data-especializaciones="{self.categoria_unas.pk}"')

    def test_deleting_collaborator_removes_user_and_specialty_when_no_appointments_exist(self):
        usuario = self.crear_personal()
        from agenda.models import ProfesionalCategoria
        ProfesionalCategoria.objects.create(
            profesional=usuario,
            categoria_id=self.categoria_unas.pk,
        )

        response = self.client.post(reverse('eliminar_personal', args=[usuario.pk]))

        self.assertRedirects(response, reverse('admin_personal'))
        self.assertFalse(Usuario.objects.filter(pk=usuario.pk).exists())
        self.assertFalse(
            ProfesionalCategoria.objects.filter(profesional_id=usuario.pk).exists(),
        )

    def test_deleting_collaborator_with_appointments_archives_instead_of_breaking_history(self):
        from agenda.models import Reserva
        from django.utils import timezone
        from datetime import timedelta

        usuario = self.crear_personal()
        servicio = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=7),
            servicio_id=servicio.pk,
            servicio_nombre=servicio.nombre,
            duracion_minutos=servicio.duracion_minutos,
            profesional=usuario,
            cliente_nombre='Clienta de prueba',
        )

        response = self.client.post(
            reverse('eliminar_personal', args=[usuario.pk]),
            {'confirmar_agenda': '1'},
        )

        self.assertRedirects(response, reverse('admin_personal'))
        usuario.refresh_from_db()
        reserva.refresh_from_db()
        self.assertFalse(usuario.is_active)
        self.assertIsNotNone(usuario.deleted_at)
        self.assertEqual(reserva.profesional_id, usuario.pk)
        self.assertNotContains(self.client.get(reverse('admin_personal')), usuario.email)

    def test_personnel_can_be_deactivated_and_reactivated(self):
        usuario = self.crear_personal()
        url = reverse('desactivar_personal', args=[usuario.pk])

        self.client.post(url)
        usuario.refresh_from_db()
        self.assertFalse(usuario.is_active)

        self.client.post(url)
        usuario.refresh_from_db()
        self.assertTrue(usuario.is_active)

    def test_last_professional_deactivation_disables_and_reactivation_restores_only_owned_future_slots(self):
        from agenda.models import Disponibilidad, ProfesionalCategoria
        usuario = self.crear_personal()
        ProfesionalCategoria.objects.create(
            profesional=usuario,
            categoria_id=self.categoria_unas.pk,
        )
        servicio = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        fecha = timezone.localdate() + timedelta(days=8)
        bloque_activo = Disponibilidad.objects.create(
            fecha_especifica=fecha,
            dia_semana=str(fecha.weekday()),
            hora_inicio='09:00',
            hora_fin='10:00',
            activo=True,
            profesional=usuario,
            servicio_id=servicio.pk,
        )
        bloque_inactivo = Disponibilidad.objects.create(
            fecha_especifica=fecha + timedelta(days=1),
            dia_semana=str((fecha + timedelta(days=1)).weekday()),
            hora_inicio='09:00',
            hora_fin='10:00',
            activo=False,
            profesional=usuario,
            servicio_id=servicio.pk,
        )
        url = reverse('desactivar_personal', args=[usuario.pk])

        self.client.post(url)
        bloque_activo.refresh_from_db()
        bloque_inactivo.refresh_from_db()
        servicio.refresh_from_db()
        self.assertFalse(bloque_activo.activo)
        self.assertTrue(bloque_activo.desactivado_por_personal)
        self.assertFalse(bloque_inactivo.activo)
        self.assertFalse(bloque_inactivo.desactivado_por_personal)
        self.assertFalse(servicio.activo)

        self.client.post(url)
        bloque_activo.refresh_from_db()
        bloque_inactivo.refresh_from_db()
        servicio.refresh_from_db()
        self.assertTrue(bloque_activo.activo)
        self.assertFalse(bloque_activo.desactivado_por_personal)
        self.assertFalse(bloque_inactivo.activo)
        self.assertTrue(servicio.activo)

    def test_service_stays_active_when_another_active_professional_has_same_specialty(self):
        from agenda.models import Disponibilidad, ProfesionalCategoria

        profesional_a = self.crear_personal()
        profesional_b = self.crear_personal(email='otra@example.com', nombre='Ana')
        for profesional in (profesional_a, profesional_b):
            ProfesionalCategoria.objects.create(
                profesional=profesional,
                categoria_id=self.categoria_unas.pk,
            )
        servicio = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        fecha = timezone.localdate() + timedelta(days=8)
        bloque = Disponibilidad.objects.create(
            fecha_especifica=fecha,
            dia_semana=str(fecha.weekday()),
            hora_inicio='09:00',
            hora_fin='10:00',
            activo=True,
            profesional=profesional_a,
            servicio_id=servicio.pk,
        )

        self.client.post(reverse('desactivar_personal', args=[profesional_a.pk]))

        servicio.refresh_from_db()
        bloque.refresh_from_db()
        self.assertTrue(servicio.activo)
        self.assertFalse(bloque.activo)
        self.assertTrue(bloque.desactivado_por_personal)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_forced_deactivation_warns_and_can_send_personalized_notice_to_account_clients(self):
        from django.core import mail
        from agenda.models import ProfesionalCategoria, Reserva

        profesional = self.crear_personal()
        ProfesionalCategoria.objects.create(
            profesional=profesional,
            categoria_id=self.categoria_unas.pk,
        )
        servicio = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        cliente = Usuario.objects.create_user(
            email='cliente@example.com',
            password='Cliente123!Test',
            nombre='Camila',
            apellido_paterno='Prueba',
            apellido_materno='Cliente',
            telefono='+56911112222',
            rol=Rol.objects.get(nombre='Cliente'),
        )
        Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(days=7),
            servicio_id=servicio.pk,
            servicio_nombre=servicio.nombre,
            duracion_minutos=servicio.duracion_minutos,
            profesional=profesional,
            cliente=cliente,
            cliente_email=cliente.email,
            cliente_nombre='Camila Prueba Cliente',
            estado='confirmada',
            origen='cliente',
        )
        url = reverse('desactivar_personal', args=[profesional.pk])

        self.client.post(url)
        profesional.refresh_from_db()
        self.assertTrue(profesional.is_active)
        self.assertEqual(len(mail.outbox), 0)

        self.client.post(url, {
            'confirmar_agenda': '1',
            'notificar_clientes': '1',
            'mensaje_clientes': 'Debido a vacaciones, coordinaremos un cambio para tu cita.',
        })
        profesional.refresh_from_db()
        self.assertFalse(profesional.is_active)
        self.assertEqual(len(mail.outbox), 1)
        self.assertEqual(mail.outbox[0].to, [cliente.email])
        self.assertIn('Debido a vacaciones', mail.outbox[0].body)
        self.assertNotIn('dejó de trabajar', mail.outbox[0].body)

    def test_agenda_professional_choices_contain_active_collaborators_only(self):
        activo = self.crear_personal()
        inactivo = self.crear_personal(
            email='inactivo@example.com',
            nombre='Ana',
        )
        inactivo.is_active = False
        inactivo.save(update_fields=['is_active'])

        from agenda.forms import DisponibilidadDiaForm, ReservaManualForm

        self.assertEqual(list(ReservaManualForm().fields['profesional'].queryset), [activo])
        self.assertEqual(list(DisponibilidadDiaForm().fields['profesional'].queryset), [activo])

    def test_agenda_professional_choices_match_service_category(self):
        from agenda.forms import DisponibilidadDiaForm, ReservaManualForm

        manicure = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        especialista_unas = self.crear_personal(email='unas@example.com')
        especialista_cabello = self.crear_personal(email='cabello@example.com', nombre='Ana')
        from agenda.models import ProfesionalCategoria
        ProfesionalCategoria.objects.create(
            profesional=especialista_unas,
            categoria_id=self.categoria_unas.pk,
        )
        ProfesionalCategoria.objects.create(
            profesional=especialista_cabello,
            categoria_id=self.categoria_cabello.pk,
        )

        data = {'servicio': str(manicure.pk)}
        self.assertEqual(
            list(ReservaManualForm(data=data).fields['profesional'].queryset),
            [especialista_unas],
        )
        self.assertEqual(
            list(DisponibilidadDiaForm(data=data).fields['profesional'].queryset),
            [especialista_unas],
        )

    def test_professional_endpoint_returns_active_matching_specialists(self):
        manicure = Servicio.objects.create(
            nombre='Manicure',
            categoria=self.categoria_unas,
            duracion_minutos=60,
            precio='12000',
        )
        especialista = self.crear_personal()
        from agenda.models import ProfesionalCategoria
        ProfesionalCategoria.objects.create(
            profesional=especialista,
            categoria_id=self.categoria_unas.pk,
        )

        response = self.client.get(
            reverse('agenda_profesionales_por_servicio'),
            {'servicio': manicure.pk},
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()['professionals'][0]['id'], especialista.pk)


class DuplicateCatalogEntryTests(TestCase):
    def setUp(self):
        self.categoria = Categoria.objects.create(nombre='Manicure', tipo='Uñas')
        administrador = Usuario.objects.create_superuser(
            email='admin.duplicados@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Prueba',
            apellido_materno='Studio',
            telefono='+56912345678',
        )
        self.client.force_login(administrador)

    def crear_imagen_producto(self):
        imagen = Image.new('RGB', (1, 1), color='white')
        contenido = BytesIO()
        imagen.save(contenido, format='PNG')
        return SimpleUploadedFile(
            'producto.png',
            contenido.getvalue(),
            content_type='image/png',
        )

    def test_identical_service_is_rejected_but_editing_itself_is_allowed(self):
        from .forms import ServicioForm

        servicio = Servicio.objects.create(
            nombre='Manicure clásica',
            categoria=self.categoria,
            descripcion='Atención tradicional',
            duracion_minutos=45,
            precio='12000',
        )
        datos = {
            'nombre': 'MANICURE CLÁSICA',
            'categoria': self.categoria.pk,
            'descripcion': '  Atención   tradicional ',
            'duracion_minutos': '45',
            'precio': '12000',
            'activo': 'true',
        }

        duplicado = ServicioForm(data=datos)
        self.assertFalse(duplicado.is_valid())
        self.assertIn('__all__', duplicado.errors)

        edicion = ServicioForm(data=datos, instance=servicio)
        self.assertTrue(edicion.is_valid(), edicion.errors)

        servicio_diferente = ServicioForm(data={**datos, 'duracion_minutos': '60'})
        self.assertTrue(servicio_diferente.is_valid(), servicio_diferente.errors)

    def test_duplicate_service_creation_request_does_not_add_a_second_record(self):
        Servicio.objects.create(
            nombre='Manicure clásica',
            categoria=self.categoria,
            descripcion='Atención tradicional',
            duracion_minutos=45,
            precio='12000',
        )

        response = self.client.post(
            reverse('crear_servicio'),
            {
                'nombre': 'MANICURE CLÁSICA',
                'categoria': self.categoria.pk,
                'descripcion': '  Atención   tradicional ',
                'duracion_minutos': '45',
                'precio': '12000',
                'activo': 'true',
            },
        )

        self.assertRedirects(response, reverse('listar_servicios'))
        self.assertEqual(Servicio.objects.filter(categoria=self.categoria).count(), 1)

    def test_identical_product_is_rejected_even_with_different_stock(self):
        from .forms import ProductoForm

        producto = Producto.objects.create(
            nombre='Aceite nutritivo',
            categoria=self.categoria,
            descripcion='Aceite para uñas',
            precio='5000',
            stock=4,
        )
        datos = {
            'nombre': producto.nombre,
            'categoria': self.categoria.pk,
            'descripcion': producto.descripcion,
            'precio': '5000',
            'stock': '99',
            'activo': 'true',
        }
        imagen = Image.new('RGB', (1, 1), color='white')
        contenido = BytesIO()
        imagen.save(contenido, format='PNG')
        archivo = SimpleUploadedFile(
            'producto.png',
            contenido.getvalue(),
            content_type='image/png',
        )

        form = ProductoForm(data=datos, files={'imagen_url': archivo})

        self.assertFalse(form.is_valid())
        self.assertIn('__all__', form.errors)

    def test_duplicate_product_creation_request_does_not_add_a_second_record(self):
        Producto.objects.create(
            nombre='Aceite nutritivo',
            categoria=self.categoria,
            descripcion='Aceite para uñas',
            precio='5000',
            stock=4,
        )

        response = self.client.post(
            reverse('crear_producto'),
            {
                'nombre': 'Aceite nutritivo',
                'categoria': self.categoria.pk,
                'descripcion': 'Aceite para uñas',
                'precio': '5000',
                'stock': '99',
                'activo': 'true',
                'imagen_url': self.crear_imagen_producto(),
            },
        )

        self.assertRedirects(response, reverse('admin_productos'))
        self.assertEqual(Producto.objects.filter(categoria=self.categoria).count(), 1)

    def test_product_with_a_different_characteristic_is_allowed(self):
        from .forms import ProductoForm

        Producto.objects.create(
            nombre='Aceite nutritivo',
            categoria=self.categoria,
            descripcion='Aceite para uñas',
            precio='5000',
            stock=4,
        )
        form = ProductoForm(
            data={
                'nombre': 'Aceite nutritivo',
                'categoria': self.categoria.pk,
                'descripcion': 'Aceite para uñas sensibles',
                'precio': '5000',
                'stock': '4',
                'activo': 'true',
            },
            files={'imagen_url': self.crear_imagen_producto()},
        )

        self.assertTrue(form.is_valid(), form.errors)

    def test_product_page_has_category_management(self):
        response = self.client.get(reverse('admin_productos'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Administrar categorías')
        self.assertContains(response, 'categoriaProductoTipo')
        self.assertContains(response, 'id="buscarCategoriaProducto"')
        self.assertContains(response, 'No hay categorías que coincidan con la búsqueda.')
        self.assertNotContains(response, 'listaCategoriasInlineProducto')
        self.assertNotContains(response, 'data-add-product-category')
        self.assertNotContains(response, '<th>Estado</th>')
        self.assertNotContains(response, 'data-bs-dismiss="modal">Cerrar')
        self.assertEqual(response.content.count(b'data-manage-categories>'), 1)
        self.assertNotContains(response, 'Crea una categoría en Servicios')


class AdminConfigurationTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_superuser(
            email='admin.configuracion@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Prueba',
            apellido_materno='Studio',
            telefono='+56912345678',
        )
        self.client.force_login(self.admin)

    def test_configuration_page_displays_profile_and_password_forms_without_account_deletion(self):
        response = self.client.get(reverse('admin_configuracion'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Segundo nombre (opcional)')
        self.assertContains(response, 'Contraseña actual')
        self.assertContains(response, 'no permite eliminar la cuenta administradora')
        self.assertNotContains(response, 'Eliminar cuenta')

    def test_profile_form_updates_the_current_administrator_only(self):
        response = self.client.post(
            reverse('admin_configuracion'),
            {
                'form_type': 'profile',
                'nombre': 'Daniela',
                'segundo_nombre': 'María',
                'apellido_paterno': 'Ejemplo',
                'apellido_materno': 'Prueba',
                'email': 'daniela.admin@example.com',
            },
        )

        self.assertRedirects(response, reverse('admin_configuracion'))
        self.admin.refresh_from_db()
        self.assertEqual(self.admin.nombre, 'Daniela')
        self.assertEqual(self.admin.segundo_nombre, 'María')
        self.assertEqual(self.admin.apellido_paterno, 'Ejemplo')
        self.assertEqual(self.admin.apellido_materno, 'Prueba')
        self.assertEqual(self.admin.email, 'daniela.admin@example.com')

    def test_password_change_requires_current_password_and_keeps_admin_logged_in(self):
        response = self.client.post(
            reverse('admin_configuracion'),
            {
                'form_type': 'password',
                'actual': 'Admin123!Test',
                'nueva': 'NuevaClave-Fuerte-86!',
                'confirmar': 'NuevaClave-Fuerte-86!',
            },
        )

        self.assertRedirects(response, reverse('admin_configuracion'))
        self.admin.refresh_from_db()
        self.assertTrue(self.admin.check_password('NuevaClave-Fuerte-86!'))
        self.assertEqual(self.client.get(reverse('admin_configuracion')).status_code, 200)

    def test_non_administrator_cannot_open_account_configuration(self):
        rol_cliente, _ = Rol.objects.get_or_create(nombre='Cliente')
        cliente = Usuario.objects.create_user(
            email='cliente.configuracion@example.com',
            password='Cliente123!Test',
            nombre='Cliente',
            apellido_paterno='Prueba',
            apellido_materno='Studio',
            telefono='+56912345679',
            rol=rol_cliente,
        )
        cliente_client = Client()
        cliente_client.force_login(cliente)

        response = cliente_client.get(reverse('admin_configuracion'))

        self.assertEqual(response.status_code, 403)

class SalesAndReminderPageTests(TestCase):
    def setUp(self):
        self.admin = Usuario.objects.create_superuser(
            email='admin.sales@example.com',
            password='Admin123!Test',
            nombre='Admin',
            apellido_paterno='Studio',
            apellido_materno='',
            telefono='+56912345678',
        )
        self.client.force_login(self.admin)

    def test_sales_page_shows_sales_and_payments_from_database(self):
        from pagos.models import Pago
        from ventas.models import Venta

        venta = Venta.objects.create(
            cliente=self.admin,
            total='15000.00',
            estado='Pendiente',
        )
        Pago.objects.create(
            venta=venta,
            monto='5000.00',
            metodo_pago='Tarjeta',
            estado_pago='Aprobado',
            transaccion_id='TX-TEST-1',
        )

        response = self.client.get(reverse('admin_ventas'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, f'#{venta.pk}')
        self.assertContains(response, 'TX-TEST-1')
        self.assertContains(response, 'Ventas registradas')
        self.assertContains(response, 'SALDO PENDIENTE')
        self.assertContains(response, 'Saldo pendiente')
        self.assertContains(response, reverse('admin_registrar_pago_saldo_venta', args=[venta.pk]))
        self.assertEqual(response.context['ventas'][0].total_pagado, Decimal('5000.00'))
        self.assertEqual(response.context['ventas'][0].saldo_pendiente, Decimal('10000.00'))
        self.assertEqual(response.context['ventas_mes_formateado'], '15.000')
        self.assertEqual(response.context['pagos_aprobados_mes_formateado'], '5.000')
        self.assertContains(response, '$15.000')
        self.assertContains(response, '$5.000')

        dashboard = self.client.get(reverse('admin_dashboard'))
        self.assertContains(dashboard, '$15.000')

        detalle = self.client.get(reverse('admin_detalle_venta', args=[venta.pk]))
        self.assertEqual(detalle.status_code, 200)
        self.assertContains(detalle, 'Pagos recibidos')

    def test_admin_registers_remaining_sale_balance_as_a_linked_payment(self):
        from pagos.models import Pago
        from ventas.models import Venta

        venta = Venta.objects.create(
            cliente=self.admin,
            total=Decimal('35000.00'),
            estado='Pendiente',
        )
        Pago.objects.create(
            venta=venta,
            monto=Decimal('20000.00'),
            metodo_pago='Pago ficticio',
            estado_pago='Aprobado',
            transaccion_id='TX-ABONO-2',
        )

        response = self.client.post(
            reverse('admin_registrar_pago_saldo_venta', args=[venta.pk]),
            {'metodo_pago': 'transferencia'},
        )

        self.assertRedirects(response, reverse('admin_ventas'))
        venta.refresh_from_db()
        pago_saldo = Pago.objects.get(venta=venta, metodo_pago='Transferencia')
        self.assertEqual(pago_saldo.monto, Decimal('15000.00'))
        self.assertEqual(venta.estado, 'Completada')

        page = self.client.get(reverse('admin_ventas'))
        self.assertEqual(page.context['ventas'][0].saldo_pendiente, Decimal('0.00'))
        self.assertContains(page, '$0')
        self.assertContains(page, 'TX-ABONO-2')
        self.assertContains(page, pago_saldo.transaccion_id)
        self.assertContains(page, '#{}'.format(venta.pk))
        self.assertNotContains(page, reverse('admin_registrar_pago_saldo_venta', args=[venta.pk]))

    def test_non_admin_cannot_register_remaining_sale_balance(self):
        from ventas.models import Venta

        venta = Venta.objects.create(
            cliente=self.admin,
            total=Decimal('10000.00'),
            estado='Pendiente',
        )
        cliente_role, _ = Rol.objects.get_or_create(nombre='Cliente')
        cliente = Usuario.objects.create_user(
            email='customer.sales@example.com',
            password='Cliente123!Test',
            nombre='Cliente',
            apellido_paterno='Prueba',
            apellido_materno='',
            telefono='+56987654321',
            rol=cliente_role,
        )
        self.client.force_login(cliente)

        response = self.client.post(
            reverse('admin_registrar_pago_saldo_venta', args=[venta.pk]),
            {'metodo_pago': 'efectivo'},
        )

        self.assertEqual(response.status_code, 403)

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_reminder_can_be_rescheduled_and_automatically_sent_at_selected_time(self):
        from agenda.models import Reserva
        from notificaciones.models import ProgramacionRecordatorio, RecordatorioEnviado
        from notificaciones.recordatorios import enviar_recordatorios_vencidos

        ahora = timezone.now()
        reserva = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Camila Pérez',
            cliente_email='camila@example.com',
            cliente_telefono='+56912345678',
            servicio_nombre='Manicure',
        )

        response = self.client.get(reverse('admin_recordatorios'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Camila Pérez')
        self.assertContains(response, '+56912345678')
        self.assertContains(response, 'PROFESIONAL')
        self.assertContains(response, 'Programar recordatorio')
        self.assertNotContains(response, 'Enviar ahora')
        self.assertNotContains(response, 'Guardar recordatorios de citas')
        programado = timezone.localtime(ahora - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
        response = self.client.post(
            reverse('programar_recordatorio', args=[reserva.pk]),
            {'tipo': 'cita', 'desfase': '48', 'programado_para': programado},
        )
        self.assertRedirects(response, reverse('admin_recordatorios'))
        tarea = next(
            tarea for tarea in response.client.get(reverse('admin_recordatorios')).context['recordatorios_cita']
            if tarea['reserva'].pk == reserva.pk and tarea['desfase'] == 48
        )
        self.assertTrue(tarea['personalizado'])
        self.assertTrue(tarea['vencido'])
        self.assertEqual(
            ProgramacionRecordatorio.objects.get(reserva=reserva, tipo='cita', desfase=48).programado_para,
            timezone.make_aware(datetime.strptime(programado, '%Y-%m-%dT%H:%M')),
        )
        self.assertEqual(enviar_recordatorios_vencidos(), (1, 0))
        self.assertEqual(enviar_recordatorios_vencidos(), (0, 0))
        self.assertEqual(
            RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='cita',
                desfase=48,
            ).count(),
            1,
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_followup_can_be_individually_scheduled_after_service_completion(self):
        from django.core import mail

        from agenda.models import Reserva
        from notificaciones.models import ProgramacionRecordatorio, RecordatorioEnviado
        from notificaciones.recordatorios import (
            construir_mensaje_recordatorio,
            enviar_recordatorios_vencidos,
        )

        ahora = timezone.now()
        reserva = Reserva.objects.create(
            fecha_hora=ahora - timedelta(hours=25),
            estado='completada',
            cliente_nombre='Sofía López',
            cliente_email='sofia@example.com',
            cliente_telefono='+56944445555',
            servicio_nombre='Tratamiento capilar',
        )

        response = self.client.get(reverse('admin_recordatorios'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Sofía López')
        self.assertContains(response, 'Programar seguimiento')
        self.assertContains(response, '+56944445555')
        programado = timezone.localtime(ahora - timedelta(minutes=5)).strftime('%Y-%m-%dT%H:%M')
        self.client.post(
            reverse('programar_recordatorio', args=[reserva.pk]),
            {'tipo': 'seguimiento', 'desfase': '24', 'programado_para': programado},
        )
        self.assertEqual(enviar_recordatorios_vencidos(), (1, 0))
        self.assertEqual(enviar_recordatorios_vencidos(), (0, 0))

        self.assertEqual(len(mail.outbox), 1)
        self.assertIn('qué tal estuvo tu atención', mail.outbox[0].subject.casefold())
        self.assertEqual(
            mail.outbox[0].body,
            construir_mensaje_recordatorio(reserva, 'seguimiento'),
        )
        self.assertIn('Servicio realizado: Tratamiento capilar', mail.outbox[0].body)
        self.assertIn('¿Viniste con acompañante?: No', mail.outbox[0].body)
        self.assertTrue(
            RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='seguimiento',
                desfase=24,
            ).exists(),
        )
        self.assertIsNotNone(
            ProgramacionRecordatorio.objects.get(
                reserva=reserva,
                tipo='seguimiento',
                desfase=24,
            ).enviado_en,
        )
        response = self.client.get(reverse('admin_recordatorios'))
        self.assertFalse(response.context['recordatorios_seguimiento'])
        self.assertEqual(len(mail.outbox), 1)

    def test_reminder_page_uses_fixed_defaults_and_no_global_configuration_form(self):
        response = self.client.get(reverse('admin_recordatorios'))
        self.assertContains(response, '48 y otro 24 horas antes')
        self.assertContains(response, '24 horas después de finalizar')
        self.assertNotContains(response, 'Horas antes de la cita para enviar cada correo')
        self.assertNotContains(response, 'Guardar seguimiento')
        self.assertNotContains(response, 'Enviar ahora')
        self.assertNotContains(response, 'dias_seguimiento')

    def test_reminder_page_builds_whatsapp_messages_for_appointments_and_followups(self):
        from agenda.models import Reserva
        from notificaciones.recordatorios import construir_mensaje_recordatorio

        ahora = timezone.now()
        rol_colaborador, _ = Rol.objects.get_or_create(nombre='Colaborador')
        profesional = Usuario.objects.create_user(
            email='profesional.recordatorio@example.com',
            password='Profesional123!Test',
            nombre='Valentina',
            apellido_paterno='Prueba',
            apellido_materno='Soto',
            telefono='+56955556666',
            rol=rol_colaborador,
        )
        cita = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Alejandra Garrido',
            cliente_email='alejandra@example.com',
            cliente_telefono='+56 9 8343 4863',
            servicio_nombre='Lifting',
            profesional=profesional,
            viene_con_acompanante=True,
        )
        seguimiento = Reserva.objects.create(
            fecha_hora=ahora - timedelta(hours=25),
            estado='completada',
            cliente_nombre='Natalia Pasten',
            cliente_email='natalia@example.com',
            cliente_telefono='9 4270 6193',
            servicio_nombre='Uñas soft gel diseños',
            profesional=profesional,
            viene_con_acompanante=True,
        )

        response = self.client.get(reverse('admin_recordatorios'))

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Avisar por WhatsApp')
        tarea_cita = next(
            tarea for tarea in response.context['recordatorios_cita']
            if tarea['reserva'].pk == cita.pk and tarea['desfase'] == 24
        )
        self.assertEqual(tarea_cita['whatsapp_numero'], '56983434863')
        mensaje_cita = tarea_cita['whatsapp_mensaje']
        self.assertIn('Alejandra', mensaje_cita)
        self.assertIn('Lifting', mensaje_cita)
        self.assertIn('¿Vienes con acompañante?: Sí', mensaje_cita)
        self.assertIn('Valentina Prueba Soto', mensaje_cita)
        self.assertIn(
            timezone.localtime(cita.fecha_hora).strftime('%d-%m-%Y'),
            mensaje_cita,
        )
        self.assertTrue(tarea_cita['usar_whatsapp'])
        self.assertContains(response, 'data-whatsapp-mensaje=')

        tarea_seguimiento = next(
            tarea for tarea in response.context['recordatorios_seguimiento']
            if tarea['reserva'].pk == seguimiento.pk
        )
        self.assertEqual(tarea_seguimiento['whatsapp_numero'], '56942706193')
        mensaje_seguimiento = tarea_seguimiento['whatsapp_mensaje']
        self.assertIn('Natalia', mensaje_seguimiento)
        self.assertIn('Uñas soft gel diseños', mensaje_seguimiento)
        self.assertIn('¿Viniste con acompañante?: Sí', mensaje_seguimiento)
        self.assertIn('Valentina Prueba Soto', mensaje_seguimiento)
        self.assertFalse(tarea_seguimiento['usar_whatsapp'])
        self.assertEqual(
            mensaje_seguimiento,
            construir_mensaje_recordatorio(seguimiento, 'seguimiento'),
        )

    def test_reminder_page_does_not_build_whatsapp_link_for_invalid_phone(self):
        from agenda.models import Reserva

        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Clienta sin teléfono válido',
            cliente_email='sin.telefono@example.com',
            cliente_telefono='12345',
            servicio_nombre='Manicure',
        )

        response = self.client.get(reverse('admin_recordatorios'))

        tarea = next(
            tarea for tarea in response.context['recordatorios_cita']
            if tarea['reserva'].pk == reserva.pk
        )
        self.assertEqual(tarea['whatsapp_numero'], '')
        self.assertNotContains(response, 'Avisar por WhatsApp')

    def test_followup_without_email_shows_whatsapp_and_skips_email_scheduler(self):
        from agenda.models import Reserva
        from notificaciones.recordatorios import enviar_recordatorios_vencidos

        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() - timedelta(hours=25),
            estado='completada',
            cliente_nombre='Natalia Pasten',
            cliente_telefono='+56942706193',
            servicio_nombre='Lifting',
        )

        response = self.client.get(reverse('admin_recordatorios'))

        self.assertEqual(response.status_code, 200)
        tarea = next(
            tarea for tarea in response.context['recordatorios_seguimiento']
            if tarea['reserva'].pk == reserva.pk
        )
        self.assertTrue(tarea['usar_whatsapp'])
        self.assertContains(response, 'Avisar por WhatsApp')
        self.assertIn('Sin correo: usa el aviso por WhatsApp', response.content.decode())
        self.assertEqual(enviar_recordatorios_vencidos(), (0, 0))

    def test_reminder_settings_cannot_be_changed_through_global_post(self):
        response = self.client.post(
            reverse('admin_recordatorios'),
            {'horas_cita': '24, 24', 'horas_seguimiento': '721'},
        )

        self.assertEqual(response.status_code, 403)

    def test_reminder_tasks_include_each_configured_offset_and_scheduled_time(self):
        from agenda.models import Reserva

        ahora = timezone.now()
        reserva = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Camila Pérez',
            cliente_email='camila@example.com',
            servicio_nombre='Manicure',
        )

        response = self.client.get(reverse('admin_recordatorios'))
        tareas = response.context['recordatorios_cita']

        self.assertEqual([tarea['desfase'] for tarea in tareas], [48, 24])
        self.assertTrue(tareas[0]['vencido'])
        self.assertFalse(tareas[1]['vencido'])
        self.assertEqual(
            tareas[0]['programado'],
            reserva.fecha_hora - timedelta(hours=48),
        )

    def test_cancelled_reservations_leave_reminders_and_rescheduled_dates_refresh_them(self):
        from agenda.models import Reserva
        from notificaciones.models import RecordatorioEnviado
        from notificaciones.recordatorios import listar_recordatorios_pendientes

        ahora = timezone.now()
        reserva = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Camila Pérez',
            cliente_email='camila@example.com',
            servicio_nombre='Manicure',
        )
        RecordatorioEnviado.objects.create(
            reserva=reserva,
            tipo='cita',
            desfase=48,
            fecha_hora_cita=reserva.fecha_hora,
            email=reserva.cliente_email,
        )
        reserva.fecha_hora += timedelta(days=1)
        reserva.save(update_fields=['fecha_hora', 'updated_at'])

        tareas = [
            tarea for tarea in listar_recordatorios_pendientes(ahora)
            if tarea['reserva'].pk == reserva.pk
        ]
        self.assertEqual([tarea['desfase'] for tarea in tareas], [48, 24])
        self.assertTrue(all(tarea['reserva'].fecha_hora == reserva.fecha_hora for tarea in tareas))

        reserva.estado = 'cancelada'
        reserva.save(update_fields=['estado', 'updated_at'])
        tareas = [
            tarea for tarea in listar_recordatorios_pendientes(ahora)
            if tarea['reserva'].pk == reserva.pk
        ]
        self.assertFalse(tareas)

    def test_reminder_date_filters_use_the_appointment_date(self):
        from agenda.models import Reserva

        ahora = timezone.now()
        cita_hoy = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Cita de hoy',
            cliente_email='hoy@example.com',
            servicio_nombre='Manicure',
        )
        cita_manana = Reserva.objects.create(
            fecha_hora=ahora + timedelta(hours=60),
            estado='confirmada',
            cliente_nombre='Cita de mañana',
            cliente_email='manana@example.com',
            servicio_nombre='Limpieza',
        )
        seguimiento_hoy = Reserva.objects.create(
            fecha_hora=ahora - timedelta(hours=5),
            duracion_minutos=30,
            estado='completada',
            cliente_nombre='Seguimiento de hoy',
            cliente_email='seguimiento-hoy@example.com',
            servicio_nombre='Manicure',
        )
        seguimiento_ayer = Reserva.objects.create(
            fecha_hora=ahora - timedelta(hours=28),
            duracion_minutos=30,
            estado='completada',
            cliente_nombre='Seguimiento de ayer',
            cliente_email='seguimiento-ayer@example.com',
            servicio_nombre='Limpieza',
        )

        response = self.client.get(
            reverse('admin_recordatorios'),
            {'fecha_cita': timezone.localtime(cita_hoy.fecha_hora).date().isoformat()},
        )
        citas = response.context['recordatorios_cita']
        self.assertEqual(
            {tarea['reserva'].pk for tarea in citas},
            {cita_hoy.pk},
        )
        self.assertEqual(
            {tarea['reserva'].pk for tarea in response.context['recordatorios_seguimiento']},
            {seguimiento_hoy.pk, seguimiento_ayer.pk},
        )

        response = self.client.get(
            reverse('admin_recordatorios'),
            {'fecha_seguimiento': timezone.localtime(seguimiento_ayer.fecha_hora).date().isoformat()},
        )
        self.assertEqual(
            {tarea['reserva'].pk for tarea in response.context['recordatorios_seguimiento']},
            {seguimiento_ayer.pk},
        )
        self.assertEqual(
            {tarea['reserva'].pk for tarea in response.context['recordatorios_cita']},
            {cita_hoy.pk, cita_manana.pk},
        )

    @override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend')
    def test_scheduled_runner_sends_due_reminders_only_once(self):
        from django.core import mail

        from agenda.models import Reserva
        from notificaciones.models import RecordatorioEnviado
        from notificaciones.recordatorios import enviar_recordatorios_vencidos

        reserva = Reserva.objects.create(
            fecha_hora=timezone.now() + timedelta(hours=36),
            estado='confirmada',
            cliente_nombre='Camila Pérez',
            cliente_email='camila@example.com',
            servicio_nombre='Manicure',
        )

        self.assertEqual(enviar_recordatorios_vencidos(), (1, 0))
        self.assertEqual(enviar_recordatorios_vencidos(), (0, 0))

        self.assertEqual(len(mail.outbox), 1)
        self.assertTrue(
            RecordatorioEnviado.objects.filter(
                reserva=reserva,
                tipo='cita',
                desfase=48,
            ).exists(),
        )

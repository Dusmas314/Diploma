from distutils.util import strtobool
from django.contrib.auth import authenticate, get_user_model
from django.core.exceptions import ValidationError, ObjectDoesNotExist
from django.core.validators import URLValidator
from django.db.models import Q, Sum, F
from requests import get
from rest_framework.generics import ListAPIView
from yaml import load as load_yaml, Loader
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from django.http import JsonResponse

from backend.models import Shop, Category, Product, ProductInfo, Parameter, ProductParameter, Order, OrderItem, Contact
from backend.serializers import UserSerializer, CategorySerializer, ShopSerializer, ProductInfoSerializer, \
    OrderItemSerializer, OrderSerializer, ContactSerializer


class RegisterAccount(APIView):
    """
    Для регистрации покупателей
    """

    def post(self, request, *args, **kwargs):
        serializer = UserSerializer(data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data, status=status.HTTP_201_CREATED)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class ConfirmAccount(APIView):
    """
    Класс для подтверждения почтового адреса
    """

    def post(self, request):
        email = request.data.get('email')
        User = get_user_model()
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            return Response({'Error': 'Пользователь с таким электронным адресом не существует'},
                            status=status.HTTP_404_NOT_FOUND)

        user.is_active = True
        user.save()

        return Response({'Message': 'Электронная почта успешно подтверждена'}, status=status.HTTP_200_OK)


class AccountDetails(APIView):
    """
    Класс для управления данными учетной записи пользователя.
    """

    # получить данные
    def get(self, request, *args, **kwargs):
        # Получение информации о текущем пользователе
        user = request.user
        serializer = UserSerializer(user)
        return Response(serializer.data)

    def post(self, request, *args, **kwargs):
        # Обновление информации о текущем пользователе
        user = request.user
        serializer = UserSerializer(user, data=request.data)
        if serializer.is_valid():
            serializer.save()
            return Response(serializer.data)
        return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class LoginAccount(APIView):
    """
    Класс для авторизации пользователей
    """

    # Авторизация методом POST
    def post(self, request, *args, **kwargs):
        email = request.data.get('email')
        password = request.data.get('password')

        if email and password:
            user = authenticate(email=email, password=password)
            if user:
                # Вернуть какой-то токен доступа или другую информацию об успешной аутентификации
                return Response({'Detail': 'Пользователь успешно аутентифицирован'}, status=status.HTTP_200_OK)

        return Response({'Detail': 'Неверные учетные данные'}, status=status.HTTP_401_UNAUTHORIZED)


class CategoryView(ListAPIView):
    """
    Класс для просмотра категорий
    """
    queryset = Category.objects.all()
    serializer_class = CategorySerializer


class ShopView(ListAPIView):
    """
    Класс для просмотра списка магазинов
    """
    queryset = Shop.objects.filter(state=True)
    serializer_class = ShopSerializer


class ProductInfoView(APIView):
    """
    Класс для поиска товаров.
    """

    def get(self, request):
        """
        Извлекает информацию о продуктах на основе указанных фильтров.
        """
        # Извлекаем параметры запроса для фильтрации
        shop_id = request.query_params.get('shop_id')
        category_id = request.query_params.get('category_id')

        # Формируем запрос для фильтрации продуктов
        query = Q(shop__state=True)  # Фильтр активных магазинов

        if shop_id:
            query &= Q(shop_id=shop_id)

        if category_id:
            query &= Q(product__category_id=category_id)

        # Получаем информацию о продуктах на основе фильтра
        products_info = ProductInfo.objects.filter(query).select_related('shop', 'product__category').prefetch_related(
            'product_parameters__parameter').distinct()

        # Сериализуем полученные данные
        serializer = ProductInfoSerializer(products_info, many=True)

        # Возвращаем сериализованные данные в качестве ответа на запрос
        return Response(serializer.data)


class BasketView(APIView):
    """
    Класс для управления корзиной пользователя.
    """

    # Получение элементов в корзине пользователя.
    def get(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Требуется вход в систему'}, status=403)

        basket = Order.objects.filter(
            user_id=request.user.id, state='basket').prefetch_related(
            'ordered_items__product_info__product__category',
            'ordered_items__product_info__product_parameters__parameter').annotate(
            total_sum=Sum(F('ordered_items__quantity') * F('ordered_items__product_info__price'))).distinct()

        serializer = OrderItemSerializer(basket, many=True)
        return Response(serializer.data)

    # Добавьте товар в корзину пользователя.
    def post(self, request):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Требуется вход в систему'}, status=403)

            # Проверка наличия всех необходимых данных в запросе
        required_fields = ['product_info_id', 'quantity']
        if not all(field in request.data for field in required_fields):
            return JsonResponse({'Status': False, 'Error': 'Отсутствие обязательных полей'}, status=400)

        try:
            product_info_id = int(request.data['product_info_id'])
            quantity = int(request.data['quantity'])
        except (KeyError, ValueError):
            return JsonResponse({'Status': False, 'Error': 'Недопустимый формат данных'}, status=400)

        # Поиск заказа пользователя в статусе "корзина"
        basket, _ = Order.objects.get_or_create(user=request.user, state='basket')

        # Создание нового пункта заказа или обновление существующего
        try:
            order_item = basket.ordered_items.get(product_info_id=product_info_id)
            order_item.quantity += quantity
            order_item.save()
        except OrderItem.DoesNotExist:
            OrderItem.objects.create(order=basket, product_info_id=product_info_id, quantity=quantity)

        return JsonResponse({'Status': True})

    # Удаление элемента из корзины пользователя.
    def delete(self, request):
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)
        item_id = request.data.get('item_id')
        try:
            item = OrderItem.objects.get(id=item_id, order__user=request.user)
            item.delete()
            return Response({'Success': 'Товар удален из корзины'}, status=status.HTTP_204_NO_CONTENT)
        except ObjectDoesNotExist:
            return Response({'Error': 'Товар не найден'}, status=status.HTTP_404_NOT_FOUND)

    # Обновление количества товара в корзине пользователя.
    def put(self, request):
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)
        item_id = request.data.get('item_id')
        quantity = request.data.get('quantity')
        try:
            item = OrderItem.objects.get(id=item_id, order__user=request.user)
            item.quantity = quantity
            item.save()
            return Response({'Success': 'Обновлено количество товаров'}, status=status.HTTP_200_OK)
        except ObjectDoesNotExist:
            return Response({'Error': 'Товар не найден'}, status=status.HTTP_404_NOT_FOUND)


class PartnerUpdate(APIView):
    """
    Класс для обновления информации о партнере.
    """
    # Обновление информации в прайс-листе партнера.
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Требуется вход в систему'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        url = request.data.get('url')
        if url:
            validate_url = URLValidator()
            try:
                validate_url(url)
            except ValidationError as e:
                return JsonResponse({'Status': False, 'Error': str(e)})
            else:
                stream = get(url).content

                data = load_yaml(stream, Loader=Loader)

                shop, _ = Shop.objects.get_or_create(name=data['shop'], user_id=request.user.id)
                for category in data['categories']:
                    category_object, _ = Category.objects.get_or_create(id=category['id'], name=category['name'])
                    category_object.shops.add(shop.id)
                    category_object.save()
                ProductInfo.objects.filter(shop_id=shop.id).delete()
                for item in data['goods']:
                    product, _ = Product.objects.get_or_create(name=item['name'], category_id=item['category'])

                    product_info = ProductInfo.objects.create(product_id=product.id,
                                                              external_id=item['id'],
                                                              model=item['model'],
                                                              price=item['price'],
                                                              price_rrc=item['price_rrc'],
                                                              quantity=item['quantity'],
                                                              shop_id=shop.id)
                    for name, value in item['parameters'].items():
                        parameter_object, _ = Parameter.objects.get_or_create(name=name)
                        ProductParameter.objects.create(product_info_id=product_info.id,
                                                        parameter_id=parameter_object.id,
                                                        value=value)

                return JsonResponse({'Status': True})

        return JsonResponse({'Status': False, 'Error': 'Не указаны все необходимые аргументы'})


class PartnerState(APIView):
    """
    Класс для управления статусом партнера.
    """
    # получить текущий статус
    def get(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Требуется вход в систему'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)

        shop = request.user.shop
        serializer = ShopSerializer(shop)
        return Response(serializer.data)

    # изменить текущий статус
    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return JsonResponse({'Status': False, 'Error': 'Требуется вход в систему'}, status=403)

        if request.user.type != 'shop':
            return JsonResponse({'Status': False, 'Error': 'Только для магазинов'}, status=403)
        state = request.data.get('state')
        if state:
            try:
                Shop.objects.filter(user_id=request.user.id).update(state=strtobool(state))
                return JsonResponse({'Status': True})
            except ValueError as error:
                return JsonResponse({'Status': False, 'Errors': str(error)})

        return JsonResponse({'Status': False, 'Errors': 'Не указаны все необходимые аргументы'})


class PartnerOrders(APIView):
    """
    Класс для получения заказов поставщиками
    """

    def get(self, request, *args, **kwargs):
        """
        Получение заказов, связанных с аутентифицированным партнером (поставщиком).
        """
        # Проверка аутентификации пользователя
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        # Проверка типа пользователя (должен быть магазином/поставщиком)
        if request.user.type != 'shop':
            return Response({'Error': 'Доступно только для магазинов'}, status=status.HTTP_403_FORBIDDEN)

        # Получение заказов поставщика
        supplier_orders = Order.objects.filter(
            user=request.user
        ).exclude(state='basket').select_related(
            'contact'
        ).annotate(
            total_sum=Sum('ordered_items__quantity' * 'ordered_items__product_info__price')
        )

        # Сериализация данных и возврат ответа
        serializer = OrderSerializer(supplier_orders, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class ContactView(APIView):
    """
    Класс для управления контактной информацией.
    """

    def get(self, request, *args, **kwargs):
        """
        Получить контактную информацию аутентифицированного пользователя.
        """
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        contacts = Contact.objects.filter(user=request.user)
        serializer = ContactSerializer(contacts, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        """
        Создать новый контакт для аутентифицированного пользователя.
        """
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        serializer = ContactSerializer(data=request.data)
        if serializer.is_valid():
            # Устанавливаем пользователя для нового контакта
            serializer.validated_data['user'] = request.user
            serializer.save()
            return Response({'Status': 'Успешно', 'Message': 'Контакт успешно создан'}, status=status.HTTP_201_CREATED)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)

    def delete(self, request, *args, **kwargs):
        """
        Удалить контакт аутентифицированного пользователя.
        """
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        contact_id = kwargs.get('contact_id')
        try:
            contact = Contact.objects.get(id=contact_id, user=request.user)
            contact.delete()
            return Response({'Status': 'Успешно', 'Message': 'Контакт успешно удален'},
                            status=status.HTTP_204_NO_CONTENT)
        except Contact.DoesNotExist:
            return Response({'Error': 'Контакт не найден'}, status=status.HTTP_404_NOT_FOUND)

    def put(self, request, *args, **kwargs):
        """
        Редактировать контакт аутентифицированного пользователя.
        """
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        contact_id = kwargs.get('contact_id')
        try:
            contact = Contact.objects.get(id=contact_id, user=request.user)
        except Contact.DoesNotExist:
            return Response({'Error': 'Контакт не найден'}, status=status.HTTP_404_NOT_FOUND)

        serializer = ContactSerializer(contact, data=request.data, partial=True)
        if serializer.is_valid():
            serializer.save()
            return Response({'Status': 'Успешно', 'Message': 'Контакт успешно отредактирован'},
                            status=status.HTTP_200_OK)
        else:
            return Response(serializer.errors, status=status.HTTP_400_BAD_REQUEST)


class OrderView(APIView):
    """
    Класс для получения и размещения заказов пользователями
    """

    def get(self, request, *args, **kwargs):
        """
        Получить список заказов пользователя.
        """
        # Проверяем, аутентифицирован ли пользователь
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        # Извлекаем заказы пользователя из базы данных
        orders = Order.objects.filter(user=request.user)

        # Сериализуем заказы
        serializer = OrderSerializer(orders, many=True)

        # Возвращаем ответ с данными о заказах
        return Response(serializer.data, status=status.HTTP_200_OK)

    def post(self, request, *args, **kwargs):
        """
        Разместить заказ из корзины пользователя.
        """
        # Проверяем, аутентифицирован ли пользователь
        if not request.user.is_authenticated:
            return Response({'Error': 'Требуется вход в систему'}, status=status.HTTP_403_FORBIDDEN)

        # Проверяем наличие необходимых данных в запросе
        required_fields = ['contact', 'items']
        if not all(field in request.data for field in required_fields):
            return Response({'Error': 'Отсутствуют необходимые данные в запросе'}, status=status.HTTP_400_BAD_REQUEST)

        # Получаем данные из запроса
        contact_id = request.data['contact']
        items = request.data['items']

        # Создаем новый заказ
        try:
            order = Order.objects.create(user=request.user, contact_id=contact_id, state='new')
        except Exception as e:
            return Response({'Error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Добавляем товары в заказ
        for item in items:
            try:
                order.items.create(product_info_id=item['product_info'], quantity=item['quantity'])
            except Exception as e:
                order.delete()
                return Response({'Error': str(e)}, status=status.HTTP_500_INTERNAL_SERVER_ERROR)

        # Возвращаем успешный ответ
        return Response({'Status': 'Успешно', 'Message': 'Заказ успешно размещен'}, status=status.HTTP_201_CREATED)


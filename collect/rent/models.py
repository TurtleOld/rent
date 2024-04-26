from django.db import models


class Rent(models.Model):
    personal_account = models.CharField(max_length=255)

    class Meta:
        ordering = ['personal_account']

    def __str__(self):
        return f'{self.personal_account}'


class ServiceInfo(models.Model):
    rent = models.ForeignKey(
        Rent,
        on_delete=models.CASCADE,
        related_name='service_info_rent',
    )
    date = models.DateField()
    type_service = models.CharField(max_length=255)
    scope_service = models.DecimalField(
        default=0,
        decimal_places=5,
        max_digits=255,
    )
    units = models.CharField(max_length=255)
    tariff = models.DecimalField(default=0, decimal_places=5, max_digits=255)
    accrued_tariff = models.DecimalField(
        default=0,
        decimal_places=5,
        max_digits=255,
    )
    recalculations = models.DecimalField(
        default=0,
        decimal_places=5,
        max_digits=255,
    )
    total = models.DecimalField(default=0, decimal_places=5, max_digits=255)

    class Meta:
        ordering = ['type_service', 'date']

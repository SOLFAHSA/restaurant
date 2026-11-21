# Canje de certificados de regalo

**VERIFIED en development.** En la revisión previa al cambio había cero documentos en Restaurant Gift Card, Certificado de Regalo, Certificado de Regalo Aplicado e Historial de Certificado de Regalo. Los métodos registrados en los pagos de facturas enlazadas a órdenes correspondían a efectivo, tarjetas bancarias o transferencias. No había saldos que migrar en este sitio.

**ANALYZED.** Grintsys ya dispone de Certificado de Regalo, la tabla de canjes en Sales Invoice y los eventos nativos de validación, envío y cancelación. Estos eventos aplican el pago a la cuenta de pasivo, bloquean el saldo al canjear, registran el movimiento y lo revierten al cancelar la factura. Restaurante valida que el método de pago nativo y su cuenta del mismo emisor estén configurados antes de invocar esa API, y entrega el importe solicitado a la factura con el remanente de pago explícito. Para canjes combinados se solicita el importe restante exacto porque la validación nativa recorta pagos excedentes.

**Estrategia de datos.** El DocType anterior se conserva para consultar instalaciones con historial. La caja usa los certificados nativos para nuevos canjes. Antes de habilitar esta versión en un sitio con tarjetas anteriores, inventariar saldos, vencimientos, empresa, código y evidencia contable. Conciliar el pasivo de apertura con contabilidad y acordar reemisión cuando el código anterior no sea compatible con los 16 dígitos y la validación Luhn. El mecanismo nativo de saldo inicial no genera el asiento de emisión. Requiere validación tributaria local para el tratamiento del saldo y su apertura. No corresponde un parche automático que convierta saldos sin ese respaldo.

**VERIFIED en pruebas.** Se verificaron el canje con pago parcial en efectivo y descuento, la cuenta de pasivo en el pago nativo, el historial enlazado a la factura, el rechazo del canje con total cero y el rechazo del efectivo excedente.

La cancelación de una factura temporal también devolvió el saldo del certificado nativo y registró el movimiento de reversión con enlace a la factura.

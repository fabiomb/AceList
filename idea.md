# AceList

Bueno, tengo una idea de nuevo proyecto, paso a detallar.

Quiero crear una pequeña aplicación para uso local exclusivamente, la idea es que uno pueda ingresar enlaces de Acestream y la aplicación se encargue de:

* Validar si existe el hash (Content ID)
* Verificar Peers/Seeds o si hay suficientes compartiéndolo
* Tratar de tomar una captura de pantalla de lo que se está transmitiendo
* Dejar disponible un botón para abrir en reproductor (ejemplo, VLC, que ya debe existir en el sistema)

El programa tiene que guardar estos datos y la fecha de cada registro porque, como es sabido, los enlaces de Acestream van muriendo por falta de emisor que cambia por otro

La aplicación tiene que permitirle al usuario

* Listar los "canales"
* Editar título, hash o borrar todo 
* Agregar nuevos
* Ordenar y filtrar
* Agregar categorías, idioma y país para cada canal 

Se asume que estará instalado el Ace Stream Media Center en la PC, la aplicación deberá funcionar para Windows, creo que si se realiza en Python podrá ser portable a otras plataformas como MacOS o Linux, pero eso no es prioritario ahora.

## Recursos

Enlaces de Acestream de referencia, algunos puede que no funcionen o no tengan peers en el momento de procesar el pedido

* 78266c15035d0ad8cbc58f821733931e1de434ab
* ecc85e5d2b6088d2d307fd0b5de4f09f089e762f
* efc60cfe5e3a349baa02bcc49f6647c21a9c3c5b
* f16d68fa5ff64f3894a45062ca28e4e66f142c6a
* 02be332ebead0484a5354fa25e97b6833b8b129e
* 895d08633bb22c2573281655cf3ca44de476cc73
* f8b0eae8fda973cf426311541d1668aa592f0a8c
* dddff67edfa7061f643ec5ae0be110169850363d
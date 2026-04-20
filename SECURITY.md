# Security Notes

Este proyecto esta pensado para operar con riesgo bajo por defecto.

## Que datos salen del repositorio

Solo se envia a OpenAI contexto de fuentes publicas:

- titulo de la fuente;
- resumen publico del feed;
- extracto corto de la pagina publica;
- metadata editorial de la consultora.

No se envia:

- documentos internos;
- CRM;
- emails de clientes;
- bases de datos;
- tokens o secretos;
- archivos locales del usuario.

## Controles activos

- allowlist de dominios para feeds y paginas fuente;
- URLs sanitizadas sin query string ni fragment;
- redaccion automatica de emails, telefonos y patrones de token antes de llamar al LLM;
- HTML generado sanitizado antes de publicarse;
- `store: false` en OpenAI Responses API;
- secretos solo por GitHub Secrets;
- workflow sin triggers de `pull_request`.

## Configuracion minima recomendada

Para hacer lo minimo posible y mantener seguridad:

1. Configura solo `OPENAI_API_KEY`.
2. Activa GitHub Pages sobre `/docs`.
3. Deja LinkedIn apagado hasta tener la app aprobada.
4. Cuando LinkedIn este listo, agrega solo:
   - `LINKEDIN_ACCESS_TOKEN`
   - `LINKEDIN_ORGANIZATION_URN`

La ruta con menor esfuerzo es arrancar con blog totalmente automatico y habilitar LinkedIn despues.

## Regla operativa

No agregues fuentes privadas ni pegues informacion interna en `config/brand.json` o en prompts.


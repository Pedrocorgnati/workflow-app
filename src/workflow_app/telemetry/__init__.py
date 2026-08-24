"""Envelopes versionados de telemetria operacional do workflow-app.

Dois envelopes, contratos DIFERENTES (invariante I4 do estudo 08-24):

- `failure_event`: explica UMA falha (o que quebrou, de que classe, em que canal);
- lifecycle (Task 15): correlaciona loop, item, fase, tier e provider efetivos.

Fundir os dois produziria um envelope que nao responde bem nenhuma das duas
perguntas. Nenhum argumento sensivel e persistido por nenhum dos dois.
"""

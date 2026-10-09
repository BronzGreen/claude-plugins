---
name: waar-hoort-dit
description: >-
  Bepaalt of code in common-base (de gedeelde basis: Go-module
  github.com/bronzgreen/common-base en de @bronzgreen/* npm-pakketten) of in
  het product (BRIDGE, CVS, een nieuw product) hoort, vóórdat je het bouwt.
  Werkt in elke BronzGreen-repo. Gebruik bij een nieuwe helper, component,
  hook, middleware, client of workflow, bij een wijziging aan iets dat
  common-base bezit (een @bronzgreen-pakket, een bevroren pad, een
  geïnstalleerde kopie), en voordat je code kopieert die misschien al in
  common-base staat. Invoke als `/common-base:waar-hoort-dit <beschrijving>`
  of zonder argument om de huidige diff te beoordelen.
---

# /common-base:waar-hoort-dit

Laat de subagent **`common-base:placement`** het oordeel geven en geef dat
letterlijk door. (In BRIDGE mag ook de projectagent `common-base-placement`;
het oordeel is hetzelfde.)

1. Bepaal de input:
   - Met argument: de beschrijving van de gebruiker.
   - Zonder argument: de wijzigingen op de huidige branch t.o.v. de
     standaardbranch (`git diff --stat origin/<default>...` plus de relevante
     hunks van nieuwe of gewijzigde niet-testbestanden).
2. Start `common-base:placement` met die input en de vraag: "Hoort dit in
   common-base of in het product?" Laat hem zelf de common-base-bron opzoeken.
3. Geef zijn antwoord (Plek / Waarom / Bestaat al / Volgende stap / Let op)
   ongewijzigd terug. Voeg niets toe dat hij niet zei.

Bij "common-base" bouw je **niet** in het product: de wijziging gaat via een
PR in `BronzGreen/common-base` (neutraal, CHANGELOG, tag), CVS neemt de tag
eerst, daarna zet één product-PR de pins (go.mod, `@bronzgreen/*`,
workflow-refs) op die versie. Bij twijfel: vraag het de common-base-eigenaar
(CODEOWNERS van common-base).

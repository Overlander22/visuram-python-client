# Entity-Label-Review – CC600 Nersingen

Stand: 2026-06-03. Read-only-Analyse, **noch keine Code-/JSON-Änderung**.

## Worum geht es
Kanäle mit zwei Werten (W1/W2) sind in `cc600_channel_mapping.json` als zwei
getrennte Zeilen gespeichert (Adresse endet auf `…1` = W1, `…2` = W2). Die
echten Labels stehen nur in der **kanonischen** Zeile (die mit befüllten
Werten). Aktuell zieht der Code das Label aus der jeweils eigenen Zeile →
Fehl-/Dublettenlabels (z.B. „Uhrzeit" für die Sonnenaufgangszeit).

**Vorgeschlagene Regel:** Label aus der kanonischen Zeile der Basis (erste 9
Stellen) – Adresse `…1` → `w1_label`, `…2` → abgeleitet aus `w2_label`/`desc`.

## Spalten
- **W**: 1=W1, 2=W2, 3=Sonderfall (Meldesymbol o.ä.)
- **Beispiel**: Wert aus der kanonischen Zeile (Snapshot)
- **Label VORSCHLAG**: fett = was nach dem Fix angezeigt würde
- **desc (Kanal)**: Gesamt-Beschreibung – Fallback/Referenz für W2-Labels

## Override-Mechanismus (geplant)
Falscher Vorschlag? Pro Kanal in der JSON optional `label_w1` / `label_w2`
setzen (überschreibt die Ableitung), analog zu `wertart`.

---

## 1. Korrekturen (54) – Label ändert sich
| Zone | cc600_adr | W | feld_id | Beispiel | Label AKTUELL | Label VORSCHLAG | desc (Kanal) |
|---|---|---|---|---|---|---|---|
| 00 | `0100000031` | 1 | Feld59 | 5:24 h:min | 00-Uhrzeit | **00-Sonnenaufgang** | Sonnenaufgang / -untergang |
| 00 | `0100000032` | 2 | Feld53 | 21:13 h:min | 00-Sonnenaufgang | **00-Sonnenuntergang** | Sonnenaufgang / -untergang |
| 00 | `0100100012` | 2 | Feld13 | 28,8 oC | 00-Außentemperatur | **00-Außentemp: 24h-Maximum** | Außentemp: 24Std-Minimum / Maximum |
| 00 | `0100400011` | 1 | Feld16 | 299 klxh | 00-Außenhelligkeit | **00-Lichtsumme** | Lichtsumme / -Vortag |
| 00 | `0100400012` | 2 | Feld65 | 383 klxh | 00-Lichtsumme | **00-Lichtsumme Vortag** | Lichtsumme / -Vortag |
| 00 | `0100900002` | 2 | Feld2 | 6 W | 00-Windgeschwindigkeit | **00-Windrichtung** | Windgeschwindigkeit / Richtung |
| 00 | `0100900502` | 2 | Feld75 | 0 nein | 00-Niederschlag | **00-Schnee** | Niederschlag / Schnee |
| 00 | `0100903022` | 2 | Feld5 | 14,0 m/s | 00-Vorzugswindrichtung | **00-Sturmschutz ab Windgeschw** | Sturmschutz / ab Windgeschw |
| 01 | `0101102021` | 1 | Container3Feld1 | 26,1 oC | 01-Raum-Mitteltemp / -Vortag | **01-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 01 | `0101122101` | 1 | Container2Feld1 | 47,3 % | 01-D-Lüftg: Stellung-Ost / West | **01-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 01 | `0101123162` | 2 | Feld46 | 12,0 m/s | 01-D-Lüftg: P-Bereich Lee | **01-D-Lüftg: Zu-Windgeschw Lee** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 01 | `0101420132` | 2 | Feld12 | 12,0 klx | 01-Schirm: Schaltpunkt Tag | **01-Schirm: Schaltpunkt Nacht Wi** | Schirm: Schaltpunkt Nacht So / Wi |
| 01 | `0101500292` | 2 | Feld30 | 10:30 h:min | 01-Bereg: Gießdauer | **01-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500312` | 2 | Feld111 | 0 aus | 01-Bereg: Gießdauer | **01-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 01 | `0101500392` | 2 | Feld44 | 13:00 h:min | 01-Bereg: Gießdauer | **01-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500492` | 2 | Feld37 | 13:30 h:min | 01-Bereg: Gießdauer | **01-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500612` | 2 | Feld114 | 0 aus | 01-Bereg: Gießdauer | **01-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 01 | `0101500691` | 1 | Feld50 | 12:00 h:min | 01-Bereg: Gießdauer | **01-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500692` | 2 | Feld48 | 13:00 h:min | 01-Bereg: Freigabe von(SA) | **01-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101502212` | 2 | Feld28 | 0:00 min:s | 01-Bereg: Magnetventil | **01-Bereg: Gießdauer** | Bereg: akt Anzahl / Gießdauer |
| 01 | `0101502312` | 2 | Feld17 | 0:00 min:s | 01-Bereg: akt Anzahl | **01-Bereg: Gießdauer** | Bereg: akt Anzahl / Gießdauer |
| 01 | `0101502412` | 2 | Feld25 | 0:00 min:s | 01-Bereg: Magnetventil | **01-Bereg: Gießdauer** | Bereg: akt Anzahl / Gießdauer |
| 01 | `0101502612` | 2 | Feld57 | 0:00 min:s | 01-Bereg: akt Anzahl | **01-Bereg: Gießdauer** | Bereg: akt Anzahl / Gießdauer |
| 02 | `0102100011` | 1 | Container7Feld1 | 28,6 oC | 02-Raumtemp-Nord / Raumtemp-Süd | **02-Raumtemp-Nord** | Raumtemp-Nord / Raumtemp-Süd |
| 02 | `0102102021` | 1 | Container20Feld1 | 27,7 oC | 02-Raum-Mitteltemp / -Vortag | **02-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 02 | `0102122101` | 1 | Container11Feld1 | 7,7 % | 02-D-Lüftg: Stellung-Ost / West | **02-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 02 | `0102123161` | 1 | Feld64 | 8,0 m/s | 02-D-Lüftg: P-Bereich Lee | **02-D-Lüftg: Zu-Windgeschw Luv** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 02 | `0102123162` | 2 | Feld73 | 12,0 m/s | 02-D-Lüftg: Zu-Windgeschw Luv | **02-D-Lüftg: Zu-Windgeschw Lee** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 02 | `0102420131` | 1 | Feld51 | 6,0 klx | 02-Schirm: Schaltpunkt Tag | **02-Schirm: Schaltpunkt Nacht So** | Schirm: Schaltpunkt Nacht So / Wi |
| 02 | `0102420132` | 2 | Feld49 | 12,0 klx | 02-Schirm: Schaltpunkt Nacht So | **02-Schirm: Schaltpunkt Nacht Wi** | Schirm: Schaltpunkt Nacht So / Wi |
| 02 | `0102420132` | 2 | Feld20 | 12,0 klx | 02-Schirm: Schaltpunkt Nacht So / Wi | **02-Schirm: Schaltpunkt Nacht Wi** | Schirm: Schaltpunkt Nacht So / Wi |
| 02 | `0102500112` | 2 | Feld113 | 0 aus | 02-Bereg: Gießdauer | **02-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 02 | `0102500192` | 2 | Feld31 | 11:45 h:min | 02-Bereg: Gießdauer | **02-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 02 | `0102500212` | 2 | Feld115 | 0 aus | 02-Bereg: Gießdauer | **02-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 02 | `0102500292` | 2 | Feld33 | 12:15 h:min | 02-Bereg: Gießdauer | **02-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 03 | `0103102021` | 1 | Container22Feld1 | 27,2 oC | 03-Raum-Mitteltemp / -Vortag | **03-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 03 | `0103122101` | 1 | Container15Feld1 | 6,1 % | 03-D-Lüftg: Stellung-Ost / West | **03-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 03 | `0103123162` | 2 | Feld77 | 12,0 m/s | 03-D-Lüftg: P-Bereich Lee | **03-D-Lüftg: Zu-Windgeschw Lee** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 03 | `0103500112` | 2 | Feld118 | 0 aus | 03-Bereg: Gießdauer | **03-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 03 | `0103500191` | 1 | Feld60 | 11:00 h:min | 03-Bereg: Gießdauer | **03-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 03 | `0103500192` | 2 | Feld62 | 11:15 h:min | 03-Bereg: Freigabe von(SA) | **03-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 03 | `0103500212` | 2 | Feld116 | 0 aus | 03-Bereg: Gießdauer | **03-Bereg: Handstart** | Bereg: Gießdauer / Handstart |
| 03 | `0103500292` | 2 | Feld34 | 11:45 h:min | 03-Bereg: Gießdauer | **03-Bereg: Freigabe bis(SU)** | Bereg: Freigabe von(SA) / bis(SU) |
| 04 | `0104102021` | 1 | Container13Feld1 | 29,1 oC | 04-Raum-Mitteltemp / -Vortag | **04-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 04 | `0104122101` | 1 | Container6Feld1 | 16,3 % | 04-D-Lüftg: Stellung-Ost / West | **04-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 04 | `0104123161` | 1 | Feld42 | 7,0 m/s | 04-D-Lüftg: P-Bereich Lee | **04-D-Lüftg: Zu-Windgeschw Luv** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 04 | `0104123162` | 2 | Feld71 | 10,0 m/s | 04-D-Lüftg: Zu-Windgeschw Luv | **04-D-Lüftg: Zu-Windgeschw Lee** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 50 | `0150511002` | 2 | Feld78 | 5 Fr | 50-GWasser: Wochentag von | **50-GWasser: Wochentag bis** | GWasser: Wochentag von / bis |
| 50 | `0150511011` | 1 | Feld15 | 10:58 h:min | 50-GWasser: Wochentag von | **50-GWasser: Versorgung von** | GWasser: Versorgung von / bis |
| 50 | `0150511012` | 2 | Feld10 | 13:00 h:min | 50-GWasser: Versorgung von | **50-GWasser: Versorgung bis** | GWasser: Versorgung von / bis |
| 50 | `0150511031` | 1 | Feld63 | 10:58 h:min | 50-GWasser: Wochentag von | **50-GWasser: Versorgung von** | GWasser: Versorgung von / bis |
| 50 | `0150511032` | 2 | Feld68 | 13:00 h:min | 50-GWasser: Versorgung von | **50-GWasser: Versorgung bis** | GWasser: Versorgung von / bis |
| 50 | `0150511051` | 1 | Feld70 | 10:58 h:min | 50-GWasser: Wochentag von | **50-GWasser: Versorgung von** | GWasser: Versorgung von / bis |
| 50 | `0150511052` | 2 | Feld79 | 13:00 h:min | 50-GWasser: Versorgung von | **50-GWasser: Versorgung bis** | GWasser: Versorgung von / bis |

---

## 2. Prüfen / Mehrdeutig (12) – Domänenwissen nötig (u.a. Suffix-3)
| Zone | cc600_adr | W | feld_id | Beispiel | Label AKTUELL | Label VORSCHLAG | desc (Kanal) |
|---|---|---|---|---|---|---|---|
| 01 | `0101112203` | 3 | Feld94 | 0,0 % | 01-Lufthzg: Einschaltdauer | **01-Lufthzg: Ventilator** | Lufthzg: Einschaltdauer / Ventilator |
| 01 | `0101502203` | 3 | Feld95 |  | 01-Bereg: Magnetventil | **01-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 01 | `0101502303` | 3 | Feld98 | 0 aus | 01-Bereg: Magnetventil | **01-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 01 | `0101502403` | 3 | Feld96 |  | 01-Bereg: Magnetventil | **01-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 01 | `0101502603` | 3 | Feld99 | 0 aus | 01-Bereg: Magnetventil | **01-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 02 | `0102112203` | 3 | Feld97 | 0,0 % | 02-Lufthzg: Einschaltdauer | **?** | Lufthzg: Einschaltdauer / Ventilator |
| 02 | `0102502103` | 3 | Feld92 |  | 02-Bereg: Magnetventil | **02-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 02 | `0102502203` | 3 | Feld91 |  | 02-Bereg: Magnetventil | **02-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 03 | `0103112203` | 3 | Feld90 | 0,0 % | 03-Lufthzg: Einschaltdauer | **03-Lufthzg: Ventilator** | Lufthzg: Einschaltdauer / Ventilator |
| 03 | `0103502103` | 3 | Feld88 |  | 03-Bereg: Magnetventil | **03-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 03 | `0103502203` | 3 | Feld93 |  | 03-Bereg: Magnetventil | **03-Bereg: Bedarf** | Bereg: Magnetventil / Bedarf |
| 50 | `0150502003` | 3 | Feld100 |  | 50-Bewässerung | **50-Bewässerung** | Bewässerung |

---

## 3. Unverändert / bereits ok (64)
<details><summary>aufklappen</summary>

| Zone | cc600_adr | W | feld_id | Beispiel | Label AKTUELL | Label VORSCHLAG | desc (Kanal) |
|---|---|---|---|---|---|---|---|
| 00 | `0100100001` | 1 | Feld3 | 23,7 oC | 00-Außentemperatur | **00-Außentemperatur** | Außentemperatur |
| 00 | `0100100011` | 1 | Feld66 | 10,7 oC | 00-Außentemp: 24Std-Minimum | **00-Außentemp: 24h-Minimum** | Außentemp: 24Std-Minimum / Maximum |
| 00 | `0100400001` | 1 | Feld9 | 6,7 klx | 00-Außenhelligkeit | **00-Außenhelligkeit** | Außenhelligkeit |
| 00 | `0100900001` | 1 | Feld8 | 2,0 m/s | 00-Windgeschwindigkeit | **00-Windgeschwindigkeit** | Windgeschwindigkeit / Richtung |
| 00 | `0100900501` | 1 | Feld36 | 0 nein | 00-Niederschlag | **00-Niederschlag** | Niederschlag / Schnee |
| 00 | `0100903011` | 1 | Feld112 | 0 aus | 00-Sturmschutz manuell | **00-Sturmschutz manuell** | Sturmschutz manuell |
| 00 | `0100903021` | 1 | Feld1 | 0 aus | 00-Sturmschutz | **00-Sturmschutz** | Sturmschutz / ab Windgeschw |
| 01 | `0101100001` | 1 | Container17Feld1 | 25,3 oC | 01-Raumtemperatur | **01-Raumtemperatur** | Raumtemperatur |
| 01 | `0101102021` | 1 | Container18Feld1 | 26,1 oC | 01-Raum-Mitteltemp | **01-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 01 | `0101112021` | 1 | Feld52 | 1,0 oC | 01-Heizung: akt Raumsollwert | **01-Heizung: akt Raumsollwert** | Heizung: akt Raumsollwert |
| 01 | `0101112201` | 1 | Feld22 | 0,0 % | 01-Lufthzg: Einschaltdauer | **01-Lufthzg: Einschaltdauer** | Lufthzg: Einschaltdauer / Ventilator |
| 01 | `0101122021` | 1 | Feld58 | 24,0 oC | 01-Lüftung: akt Raumsollwert | **01-Lüftung: akt Raumsollwert** | Lüftung: akt Raumsollwert |
| 01 | `0101122101` | 1 | Container1Feld1 | 47,3 % | 01-D-Lüftg: Stellung-Ost | **01-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 01 | `0101123161` | 1 | Feld72 | 8,0 m/s | 01-D-Lüftg: Zu-Windgeschw Luv | **01-D-Lüftg: Zu-Windgeschw Luv** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 01 | `0101420101` | 1 | Feld74 | 35,0 klx | 01-Schirm: Schaltpunkt Tag | **01-Schirm: Schaltpunkt Tag** | Schirm: Schaltpunkt Tag |
| 01 | `0101420131` | 1 | Feld55 | 5,0 klx | 01-Schirm: Schaltpunkt Nacht So | **01-Schirm: Schaltpunkt Nacht So** | Schirm: Schaltpunkt Nacht So / Wi |
| 01 | `0101422101` | 1 | Container4Feld1 | 0,0 % | 01-Schirm: Stellung | **01-Schirm: Stellung** | Schirm: Stellung / Betriebsart |
| 01 | `0101500211` | 1 | Feld117 | 15:00 min:s | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer / Handstart |
| 01 | `0101500221` | 1 | Feld26 |  | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer / Handstart |
| 01 | `0101500291` | 1 | Feld27 | 10:15 h:min | 01-Bereg: Freigabe von(SA) | **01-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500321` | 1 | Feld24 | 15:00 min:s | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer |
| 01 | `0101500391` | 1 | Feld47 | 12:00 h:min | 01-Bereg: Freigabe von(SA) | **01-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500411` | 1 | Feld110 | 15:00 min:s | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer / Handstart |
| 01 | `0101500421` | 1 | Feld80 |  | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer / Handstart |
| 01 | `0101500491` | 1 | Feld23 | 13:00 h:min | 01-Bereg: Freigabe von(SA) | **01-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 01 | `0101500621` | 1 | Feld41 | 60:00 min:s | 01-Bereg: Gießdauer | **01-Bereg: Gießdauer** | Bereg: Gießdauer |
| 01 | `0101502201` | 1 | Feld95 | 0 aus | 01-Bereg: Magnetventil | **01-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 01 | `0101502401` | 1 | Feld96 | 0 aus | 01-Bereg: Magnetventil | **01-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 02 | `0102100001` | 1 | Container28Feld1 | 28,1 oC | 02-Raumtemperatur | **02-Raumtemperatur** | Raumtemperatur |
| 02 | `0102100011` | 1 | Container29Feld1 | 28,6 oC | 02-Raumtemp-Nord | **02-Raumtemp-Nord** | Raumtemp-Nord / Raumtemp-Süd |
| 02 | `0102102021` | 1 | Container19Feld1 | 27,7 oC | 02-Raum-Mitteltemp | **02-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 02 | `0102112021` | 1 | Feld67 | -3,0 oC | 02-Heizung: akt Raumsollwert | **02-Heizung: akt Raumsollwert** | Heizung: akt Raumsollwert |
| 02 | `0102112201` | 1 | Feld29 | 0,0 % | 02-Lufthzg: Einschaltdauer | **02-Lufthzg: Einschaltdauer** | Lufthzg: Einschaltdauer / Ventilator |
| 02 | `0102122021` | 1 | Feld54 | 28,0 oC | 02-Lüftung: akt Raumsollwert | **02-Lüftung: akt Raumsollwert** | Lüftung: akt Raumsollwert |
| 02 | `0102122101` | 1 | Container10Feld1 | 7,7 % | 02-D-Lüftg: Stellung-Ost | **02-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 02 | `0102420101` | 1 | Feld4 | 50,0 klx | 02-Schirm: Schaltpunkt Tag | **02-Schirm: Schaltpunkt Tag** | Schirm: Schaltpunkt Tag |
| 02 | `0102422101` | 1 | Container8Feld1 | 0,0 % | 02-Schirm: Stellung | **02-Schirm: Stellung** | Schirm: Stellung / Betriebsart |
| 02 | `0102500121` | 1 | Feld38 | 8:00 min:s | 02-Bereg: Gießdauer | **02-Bereg: Gießdauer** | Bereg: Gießdauer |
| 02 | `0102500191` | 1 | Feld32 | 11:30 h:min | 02-Bereg: Freigabe von(SA) | **02-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 02 | `0102500221` | 1 | Feld6 | 15:00 min:s | 02-Bereg: Gießdauer | **02-Bereg: Gießdauer** | Bereg: Gießdauer |
| 02 | `0102500291` | 1 | Feld35 | 11:40 h:min | 02-Bereg: Freigabe von(SA) | **02-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 02 | `0102502101` | 1 | Feld92 | 0 aus | 02-Bereg: Magnetventil | **02-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 02 | `0102502201` | 1 | Feld91 | 0 aus | 02-Bereg: Magnetventil | **02-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 03 | `0103100001` | 1 | Container9Feld1 | 28,1 oC | 03-Raumtemperatur | **03-Raumtemperatur** | Raumtemperatur |
| 03 | `0103102021` | 1 | Container21Feld1 | 27,2 oC | 03-Raum-Mitteltemp | **03-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 03 | `0103112021` | 1 | Feld19 | -3,0 oC | 03-Heizung: akt Raumsollwert | **03-Heizung: akt Raumsollwert** | Heizung: akt Raumsollwert |
| 03 | `0103112201` | 1 | Feld21 | 0,0 % | 03-Lufthzg: Einschaltdauer | **03-Lufthzg: Einschaltdauer** | Lufthzg: Einschaltdauer / Ventilator |
| 03 | `0103122021` | 1 | Feld76 | 28,0 oC | 03-Lüftung: akt Raumsollwert | **03-Lüftung: akt Raumsollwert** | Lüftung: akt Raumsollwert |
| 03 | `0103122101` | 1 | Container14Feld1 | 6,1 % | 03-D-Lüftg: Stellung-Ost | **03-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 03 | `0103123161` | 1 | Feld56 | 8,0 m/s | 03-D-Lüftg: Zu-Windgeschw Luv | **03-D-Lüftg: Zu-Windgeschw Luv** | D-Lüftg: Zu-Windgeschw Luv / Lee |
| 03 | `0103500121` | 1 | Feld39 | 8:00 min:s | 03-Bereg: Gießdauer | **03-Bereg: Gießdauer** | Bereg: Gießdauer |
| 03 | `0103500221` | 1 | Feld40 | 20:00 min:s | 03-Bereg: Gießdauer | **03-Bereg: Gießdauer** | Bereg: Gießdauer |
| 03 | `0103500291` | 1 | Feld7 | 11:10 h:min | 03-Bereg: Freigabe von(SA) | **03-Bereg: Freigabe von(SA)** | Bereg: Freigabe von(SA) / bis(SU) |
| 03 | `0103502101` | 1 | Feld88 | 0 aus | 03-Bereg: Magnetventil | **03-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 03 | `0103502201` | 1 | Feld93 | 0 aus | 03-Bereg: Magnetventil | **03-Bereg: Magnetventil** | Bereg: Magnetventil / Bedarf |
| 04 | `0104100001` | 1 | Container23Feld1 | 30,6 oC | 04-Raumtemperatur | **04-Raumtemperatur** | Raumtemperatur |
| 04 | `0104102021` | 1 | Container24Feld1 | 29,1 oC | 04-Raum-Mitteltemp | **04-Raum-Mitteltemp** | Raum-Mitteltemp / -Vortag |
| 04 | `0104122021` | 1 | Feld43 | 30,0 oC | 04-Lüftung: akt Raumsollwert | **04-Lüftung: akt Raumsollwert** | Lüftung: akt Raumsollwert |
| 04 | `0104122101` | 1 | Container5Feld1 | 16,3 % | 04-D-Lüftg: Stellung-Ost | **04-D-Lüftg: Stellung-Ost** | D-Lüftg: Stellung-Ost / West |
| 05 | `0105100001` | 1 | Feld61 | 27,9 oC | 05-Raumtemperatur | **05-Raumtemperatur** | Raumtemperatur |
| 50 | `0150511001` | 1 | Feld14 | 1 Mo | 50-GWasser: Wochentag von | **50-GWasser: Wochentag von** | GWasser: Wochentag von / bis |
| 50 | `0150511021` | 1 | Feld11 | 6 Sa | 50-GWasser: Wochentag von | **50-GWasser: Wochentag von** | GWasser: Wochentag von / bis |
| 50 | `0150511041` | 1 | Feld69 | 7 So | 50-GWasser: Wochentag von | **50-GWasser: Wochentag von** | GWasser: Wochentag von / bis |
| 91 | `0191112101` | 1 | Feld89 | 0 aus | 91-Pumpe | **91-Pumpe** | Pumpe |
</details>

---

## 4. Nachkorrektur W2-Container-Felder

In der ursprünglichen Tabelle wurden Container-**W2**-Felder (gespeichert als
`feld_id_w2` einer `…1`-Adresszeile) irreführend mit „W=1" und dem W1-Beispielwert
gezeigt. Dadurch erhielten sie beim Review das W1-Label. Anhand der `w2_label`/
`w2_value` korrigiert:

| feld_id | W2-Wert | Label (korrigiert) |
|---|---|---|
| Container7Feld1 | 27,6 oC | 02-Raumtemp-Süd |
| Container3Feld1 | 23,6 oC | 01-Raum-Mitteltemp Vortag |
| Container20Feld1 | 25,1 oC | 02-Raum-Mitteltemp Vortag |
| Container22Feld1 | 25,1 oC | 03-Raum-Mitteltemp Vortag |
| Container13Feld1 | 27,1 oC | 04-Raum-Mitteltemp Vortag |
| Container2Feld1 | 47,3 % | 01-D-Lüftg: Stellung-West |
| Container11Feld1 | 0,0 % | 02-D-Lüftg: Stellung-West |
| Container15Feld1 | 0,0 % | 03-D-Lüftg: Stellung-West |
| Container6Feld1 | 0,0 % | 04-D-Lüftg: Stellung-West |

(`Feld20` „Schirm: Schaltpunkt Nacht Wi" war bereits korrekt.)

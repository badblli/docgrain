# Hospitality record vocabulary

`taxonomy.json` is the machine-readable version of these boundaries, included in
every extraction pass. The all-collection pass receives every collection rule;
focused passes receive their definition plus the shared boundary rules. Source
text remains untrusted data, and every emitted fact still needs verified evidence.

| Collection | Boundary | Record granularity | Neutral example |
| --- | --- | --- | --- |
| `property` | Property identity, address, category, general description | One identified property, never the entire document | Example Lodge, four stars |
| `room_type` | Bookable category; size, capacity, beds, view, room amenities | One room category; bed alternatives in one list | Garden room, double or two single beds |
| `outlet` | Named restaurant or bar | One outlet, with its hours and reservation terms | Garden restaurant, 07:00–10:00 |
| `activity` | Event, sport or programme | One activity, with schedule and age range | Morning yoga, ages 16+ |
| `facility` | Property-wide place, amenity or available service | One named facility/amenity; `kind` can be absent | Outdoor pool; property-wide Wi-Fi; parking |
| `policy` | Permission, prohibition, requirement or operating rule | One rule/topic with its scope, conditions and exceptions | No pets except assistance dogs |
| `contact` | Communication endpoint or contact address | One endpoint/purpose | Reservations: booking@example.invalid |
| `service_price` | Explicitly priced service option, including explicit free/zero | One option **and time limit**, with amount/currency/unit/conditions | Late check-out until 18:00, 30 EUR; until 23:00, 60 EUR |

Availability alone is a facility fact, not a policy. A smoking restriction is a
policy. A parking fee is a service price; parking availability is a facility and
parking restrictions may separately be a policy. Distinct facts about one thing
may therefore support records in more than one collection. Do not invent fees
from availability, or invent rules from fees.

Room-only Wi-Fi, toiletries and a baby cot belong in `room_type.features`.
Property-wide Wi-Fi belongs in `facility`. A priced cot rental also supports a
`service_price`. An unpriced room amenity is not a service price.

Keep price tiers, quantities, age bands, durations, currencies and time limits
separate. Include the source-stated discriminator in each service price's name
and conditions so same-name collapse cannot combine them. Two late check-out
options until 18:00 and 23:00 remain separate even if their amounts agree.
Never duplicate an outlet or activity for each opening interval.

## Comparison and review

Comparison keys normalize whitespace, case, diacritics, numeric/unit spelling
and clock/range spelling. Room feature and bed lists split `veya`, `or`, `oder`,
`или`, commas and semicolons; ordering does not create a conflict. Free prose is
not split into lists. Different numbers, units, currencies, times, negations and
languages remain distinct. Stored source values and exact quotations are retained;
equivalent values combine evidence before conflict detection, without acceptance.

The offline scorer uses key-fact overlap for `text`, `description`, `conditions`
and `applies_to` with a default 0.7 threshold. Numbers, times, units/currencies,
negations and exception markers must agree. A small deterministic noun vocabulary
recognizes common paraphrases; unknown words stay literal. This is a heuristic,
not a semantic correctness guarantee. Missing facts and unsupported evidence fail.

`neighbours` in the JSON lists plausible classification confusions, not alternative
valid types. Alignment prefers the expected type, then allows a neighbouring type
with a sufficiently similar name. Type mismatches are reported separately and
remain failures in strict correctness and the D4 target. Content correctness is
reported as an additional diagnostic; it cannot hide classification errors.

Golden collection and granularity disagreements need lead review. Never change
the frozen golden to agree with predictions.

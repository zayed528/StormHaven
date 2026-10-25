// Spanish for the sentences the BACKEND engines write in English (risk factors, range text, steps, drivers,
// trust lists, alert reasons, escalations, the offline chat reply, the fixed 911 message).   Owner: Nandan
// Why here: those sentences live in teammates' engine files (risk.py, restoration.py, alerts.py, agent.py),
// so the frontend translates them for display instead of changing their code. Each rule mirrors one backend
// template; if a template changes, its sentence simply shows in English (never blank, never wrong numbers).
// Guidance text is NOT translated here: the backend sends it in Spanish (guidance_library.yaml text_es).
// TODO: native-speaker review (Task 10).

// Equipment names from core/privacy.py (FRIENDLY / SHORT / friendly_name fallback).
const EQUIP = {
  "the substation serving your area": "la subestación que abastece su zona",
  "the main circuit breaker for your area": "el interruptor principal de su zona",
  "an automatic switch on the main line": "un interruptor automático en la línea principal",
  "the fuse protecting your street": "el fusible que protege su calle",
  "the transformer serving your home": "el transformador que abastece su casa",
  "a voltage transformer on the line serving your area": "un transformador de voltaje en la línea que abastece su zona",
  "equipment upstream of you": "un equipo antes de su casa en la línea",
};
const SHORT = {
  substation: ["subestación", "otra"], "circuit breaker": ["interruptor principal", "otro"],
  "automatic switch": ["interruptor automático", "otro"], fuse: ["fusible", "otro"],
  transformer: ["transformador", "otro"], "voltage transformer": ["transformador de voltaje", "otro"],
  "piece of equipment": ["equipo", "otro"],
};
const equip = (s) => {
  if (EQUIP[s]) return EQUIP[s];
  const m = /^another (.+) further up the line$/.exec(s);
  if (m && SHORT[m[1]]) return `${SHORT[m[1]][1]} ${SHORT[m[1]][0]} más arriba en la línea`;
  return s;
};

const BAND = { Low: "bajo", Moderate: "moderado", High: "alto", "Very High": "muy alto", Unknown: "desconocido" };
const CONF = { High: "alta", Medium: "media", Low: "baja" };
const ROAD = { normal: "normal", limited: "limitado", blocked: "bloqueado" };

// Durations from restoration._fmt: "3.3 days" / "10 hours".
const dur = (s) => s.replace(/^([\d.]+) days?$/, "$1 días").replace(/^(\d+) hours?$/, (_, n) => `${n} ${n === "1" ? "hora" : "horas"}`);
// "less than 1%" / "about 9%" from risk._pct_text.
const pct = (s) => s.replace(/^less than 1%$/, "menos del 1%").replace(/^about (\d+)%$/, "alrededor del $1%");

// The fixed safety message (backend ai/prompts.py SAFETY_911), without its "SAFETY:" prefix.
export const SAFETY_911_EN = "If a power line is down, something is sparking or on fire, or someone needs urgent medical help, call 911 now. Stay at least 30 feet away from downed lines and assume they are live.";
const SAFETY_911_ES = "Si hay un cable eléctrico caído, algo está echando chispas o en llamas, o alguien necesita ayuda médica urgente, llame al 911 ahora. Manténgase al menos a 30 pies de los cables caídos y suponga que tienen corriente.";

// Whole sentences that never vary.
const EXACT = {
  [SAFETY_911_EN]: SAFETY_911_ES,
  // risk.py
  "This storm is forecast to be stronger than a typical storm.": "Se pronostica que esta tormenta será más fuerte que una tormenta típica.",
  "This storm is forecast to be milder than a typical storm.": "Se pronostica que esta tormenta será más leve que una tormenta típica.",
  "Little storm history for the equipment that serves you.": "Hay poco historial de tormentas para el equipo que le da servicio.",
  "We matched your area, not your exact address.": "Identificamos su zona, no su dirección exacta.",
  "Demo network: synthetic data.": "Red de demostración: datos sintéticos.",
  "Our very high estimates have run high in past storms: read this as 'likely', not 'certain'.":
    "En tormentas pasadas, nuestras estimaciones muy altas han resultado algo exageradas: entiéndalo como 'probable', no 'seguro'.",
  "We couldn't match this location to our network data.": "No pudimos relacionar esta ubicación con los datos de nuestra red.",
  "No prediction made.": "No se hizo ninguna predicción.",
  "You enter your premise ID or select your area on the map.": "Ingresa su número de servicio o selecciona su zona en el mapa.",
  "Storm strength is a scenario input, not a live forecast.": "La fuerza de la tormenta es un dato del escenario, no un pronóstico en vivo.",
  "Equipment damage rates come from past storms in this area.": "Las tasas de daño del equipo provienen de tormentas pasadas en esta zona.",
  "The storm track or strength changes.": "Cambia la trayectoria o la fuerza de la tormenta.",
  "Crews pre-position or reconfigure the network before the storm.": "Las cuadrillas se posicionan con anticipación o reconfiguran la red antes de la tormenta.",
  // restoration.py
  "We can't estimate restoration for this location yet.": "Todavía no podemos estimar la restauración para esta ubicación.",
  "Location not matched to network.": "La ubicación no coincide con la red.",
  "Select your area on the map.": "Seleccione su zona en el mapa.",
  "Repair times use AEP's standard labor hours plus travel and setup time.":
    "Los tiempos de reparación usan las horas de trabajo estándar de AEP más el tiempo de traslado y preparación.",
  "Repair times use placeholder labor hours until AEP's labor sheet is loaded.":
    "Los tiempos de reparación usan horas de trabajo provisionales hasta que se cargue la hoja de trabajo de AEP.",
  "Crews restore the repairs that bring back the most customers first.":
    "Las cuadrillas hacen primero las reparaciones que devuelven la electricidad a más clientes.",
  // alerts.py
  "Enrolled in alerts.": "Inscrito en las alertas.",
  "Not enrolled in alerts yet — sign up to receive them.": "Todavía no está inscrito en las alertas; inscríbase para recibirlas.",
  "Has a contact channel on file.": "Tiene un medio de contacto registrado.",
  "No phone or email on file.": "No hay teléfono ni correo electrónico registrado.",
  "Declared medical or critical-facility need: priority alerts and human follow-up.":
    "Necesidad médica o de instalación crítica declarada: alertas prioritarias y seguimiento por una persona.",
  "Voice call + human agent follow-up; share nearest power/shelter options":
    "Llamada de voz y seguimiento por un agente; compartir las opciones más cercanas de electricidad o refugio",
  "Proactive apology + new estimate + reason": "Disculpa proactiva, nueva estimación y motivo",
  "Show 911 + safety message immediately; route to emergency queue":
    "Mostrar de inmediato el 911 y el mensaje de seguridad; enviar a la fila de emergencias",
  "Fall back to area-level message; offer human contact": "Usar un mensaje a nivel de zona; ofrecer contacto con una persona",
  // console.py / planner: escalation triggers and operator equipment labels
  "Would trigger for any customer who has declared a medical need (none assumed)":
    "Se activaría para cualquier cliente que haya declarado una necesidad médica (no se supone ninguna)",
  "Model confidence Low or location unmatched": "Confianza del modelo baja o ubicación no encontrada",
  "Circuit breaker": "Interruptor principal", "Automatic switch": "Interruptor automático", "Fuse": "Fusible",
  "Substation": "Subestación", "Transformer": "Transformador", "Voltage transformer": "Transformador de voltaje",
  // ai/agent.py offline replies
  "I couldn't match your location to our data, so I can't make a reliable prediction. Please check AEP's official outage map.":
    "No pude relacionar su ubicación con nuestros datos, así que no puedo hacer una predicción confiable. Consulte el mapa oficial de apagones de AEP.",
  "I'm having trouble answering right now. Please check AEP's outage map or contact AEP directly.":
    "Tengo problemas para responder en este momento. Consulte el mapa de apagones de AEP o comuníquese directamente con AEP.",
};

// Templated sentences: [pattern, (match groups) => Spanish]. Tried in order; first match wins.
const RULES = [
  // risk.py factors
  [/^Based on past storms, the chance that (.+) is damaged in a storm like this one is (.+)\.$/,
    (who, p) => `Según tormentas pasadas, la probabilidad de que se dañe ${equip(who)} en una tormenta como esta es ${pct(p)}.`],
  [/^Your power passes through (\d+) pieces of equipment; each is a place a storm can cause damage\.$/,
    (n) => `Su electricidad pasa por ${n} equipos; en cada uno, una tormenta puede causar daños.`],
  [/^Only a few past storms were this (severe|mild), so this estimate rests on very little history\.$/,
    (k) => `Pocas tormentas pasadas han sido tan ${k === "severe" ? "severas" : "leves"}, así que esta estimación se basa en muy poco historial.`],
  // restoration.py range text
  [/^If you lose power, most likely (.+?) to (.+?) \(best guess about (.+?)\)\.$/,
    (a, b, c) => `Si se queda sin luz, lo más probable es que tarde entre ${dur(a)} y ${dur(b)} (mejor estimación: alrededor de ${dur(c)}).`],
  [/^Our estimate: power back in about (.+?) to (.+?) \(best guess about (.+?)\)\. This is a model estimate, not a confirmed restoration time\.$/,
    (a, b, c) => `Nuestra estimación: la electricidad volvería en un plazo de entre ${dur(a)} y ${dur(b)} (mejor estimación: alrededor de ${dur(c)}). Es una estimación del modelo, no una hora de restauración confirmada.`],
  // restoration.py steps + drivers + assumptions
  [/^If damaged, crews repair (.+) \(serves about (\d+)% of your area\)\.$/,
    (who, n) => `Si hay daños, las cuadrillas reparan ${equip(who)} (abastece aproximadamente el ${n}% de su zona).`],
  [/^About (\d+) hours? (sooner|later) (.+)\.$/, (n, dir, cond) => {
    const c = { "if 50% more crews are available": "si hay un 50% más de cuadrillas disponibles",
                "if fallen trees block roads": "si los árboles caídos bloquean las carreteras",
                "if the storm is stronger than forecast": "si la tormenta es más fuerte de lo pronosticado" }[cond];
    return c ? `Aproximadamente ${n} ${n === "1" ? "hora" : "horas"} ${dir === "sooner" ? "antes" : "después"} ${c}.` : null;
  }],
  [/^(\d+) crews available storm-wide\.$/, (n) => `${n} cuadrillas disponibles en toda la zona afectada.`],
  [/^Road access: (normal|limited|blocked)\.$/, (r) => `Acceso por carretera: ${ROAD[r]}.`],
  [/^Each repair crew has (\d+) people\.$/, (n) => `Cada cuadrilla de reparación tiene ${n} personas.`],
  // alerts.py escalation triggers (console)
  [/^Declared medical need and estimated outage > (\d+) hrs$/, (h) => `Necesidad médica declarada y apagón estimado de más de ${h} h`],
  // planner storm names: "Feb 2025 storm"
  [/^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) (\d{4}) storm$/, (m, y) => `Tormenta de ${{ Jan: "ene.", Feb: "feb.", Mar: "mar.",
    Apr: "abr.", May: "mayo", Jun: "jun.", Jul: "jul.", Aug: "ago.", Sep: "sept.", Oct: "oct.", Nov: "nov.", Dec: "dic." }[m]} ${y}`],
  // alerts.py eligibility reasons
  [/^Outage risk is (.+?) — meets the pre-storm alert threshold\.$/,
    (b) => `El riesgo de apagón es ${BAND[b] ?? b}: cumple el umbral para recibir alertas antes de la tormenta.`],
  [/^Outage risk is (.+?) — below the pre-storm threshold; you'll still get outage alerts\.$/,
    (b) => `El riesgo de apagón es ${BAND[b] ?? b}: está por debajo del umbral para alertas antes de la tormenta, pero igual recibirá alertas de apagón.`],
];

const OFFLINE_TAIL = " This is an estimate, not a confirmed AEP restoration time.";

// One sentence (or the offline chat reply) -> Spanish; unknown text is returned unchanged.
export function toEs(text) {
  if (!text) return text;
  if (EXACT[text]) return EXACT[text];
  for (const [re, fn] of RULES) {
    const m = re.exec(text);
    if (m) { const out = fn(...m.slice(1)); if (out) return out; }
  }
  // ai/agent.py offline reply: "Your outage risk is X (Y confidence). {top factor} {range text} This is an estimate..."
  const m = /^Your outage risk is (.+?) \((High|Medium|Low) confidence\)\. ?([\s\S]*)$/.exec(text);
  if (m) {
    let rest = m[3].endsWith(OFFLINE_TAIL) ? m[3].slice(0, -OFFLINE_TAIL.length) : m[3];
    // rest = "{factor} {range text}": split where the range sentence starts and translate each part.
    const i = Math.max(rest.indexOf("If you lose power,"), rest.indexOf("Our estimate:"));
    const parts = i > 0 ? [rest.slice(0, i).trim(), rest.slice(i)] : [rest];
    rest = parts.filter(Boolean).map(toEs).join(" ");
    return `Su riesgo de apagón es ${BAND[m[1]] ?? m[1]} (confianza ${CONF[m[2]]}). ${rest}`
      + (m[3].endsWith(OFFLINE_TAIL) ? " Es una estimación, no una hora de restauración confirmada por AEP." : "");
  }
  return text;
}

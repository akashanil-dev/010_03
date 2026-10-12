// Malayalam wording for each kind of issue, for warehouse and floor staff.
// Fixed templates (not machine translation), so the wording is predictable.
// Document names and trade terms stay in English, as they are used in practice.

const ML_FIELDS = {
  quantity: "അളവ്",
  cartons: "കാർട്ടണുകളുടെ എണ്ണം",
  net_weight: "നെറ്റ് വെയ്റ്റ്",
  gross_weight: "ഗ്രോസ് വെയ്റ്റ്",
  hs_code: "HS കോഡ്",
  exporter_name: "എക്സ്പോർട്ടറുടെ പേര്",
  consignee_name: "കൺസൈനിയുടെ പേര്",
  iec: "IEC നമ്പർ",
  gstin: "GSTIN",
  port_of_loading: "ലോഡിങ് പോർട്ട്",
  port_of_discharge: "ഡിസ്ചാർജ് പോർട്ട്",
  incoterms: "Incoterms",
  container_no: "കണ്ടെയ്നർ നമ്പർ",
  fob_value: "FOB മൂല്യം",
  invoice_ref: "Invoice നമ്പർ",
  po_ref: "PO നമ്പർ",
};

function mlMessage(c) {
  const out = (c.values || []).filter((v) => v.outlier);
  const ref = (c.values || []).find((v) => !v.outlier);
  if (c.id === "cross:quantity") {
    const [po, inv] = c.values || [];
    if (!po || !inv) return null;
    return c.status === "error"
      ? `Invoice-ൽ ${inv.display} ബിൽ ചെയ്തിട്ടുണ്ട്, പക്ഷേ PO-യിൽ ഓർഡർ ചെയ്തത് ${po.display} മാത്രമാണ്. ഓർഡറിലും കൂടുതൽ അയക്കാൻ buyer-ന്റെ രേഖാമൂലമുള്ള സമ്മതം (പുതുക്കിയ PO) വേണം.`
      : `Invoice-ൽ ${inv.display} മാത്രമേ ബിൽ ചെയ്തിട്ടുള്ളൂ, PO-യിൽ ${po.display} ഓർഡർ ചെയ്തിട്ടുണ്ട്. ഇത് partial shipment ആണെങ്കിൽ PO-യും LC-യും അത് അനുവദിക്കുന്നുണ്ടോ എന്ന് ഉറപ്പാക്കുക.`;
  }
  if (c.id === "cross:description") {
    const v = out[0];
    return v ? `${v.doc_name}-ലെ ചരക്കിന്റെ വിവരണം വളരെ ചുരുക്കമാണ് ("${v.raw}"). കൂടുതൽ വിശദമായ വിവരണം വേണോ എന്ന് തീരുമാനിക്കുക.` : null;
  }
  if (c.id.startsWith("cross:") && out.length && ref) {
    const field = ML_FIELDS[c.field] || c.field;
    const docs = out.map((v) => v.doc_name).join(", ");
    return `${docs}-ൽ ${field} ${out[0].display} എന്നാണ്, എന്നാൽ മറ്റ് രേഖകളിൽ ${ref.display} ആണ്. ${docs} പരിശോധിച്ച് തിരുത്തുക.`;
  }
  if (c.id === "math:invoice") return `Invoice-ലെ തുകകൾ ഒത്തുപോകുന്നില്ല: ${c.message} Invoice വീണ്ടും കണക്കാക്കുക.`;
  if (c.id === "math:packing") return `Packing list-ലെ ഭാരം ഒത്തുപോകുന്നില്ല: ${c.message} കാർട്ടണുകൾ വീണ്ടും എണ്ണി നോക്കുക.`;
  if (c.id === "comp:lut") return "Shipping bill-ൽ LUT പ്രകാരമുള്ള കയറ്റുമതിയാണ്, പക്ഷേ invoice-ൽ LUT ARN ഇല്ല. Invoice-ൽ LUT ARN ചേർക്കുക.";
  if (c.id.startsWith("comp:date")) {
    const [a, b] = c.values || [];
    return a && b ? `${b.doc_name}-ന്റെ തീയതി (${b.raw}) ${a.doc_name}-ന്റെ തീയതിക്ക് (${a.raw}) മുമ്പാണ്. തീയതി പരിശോധിക്കുക.` : null;
  }
  if (c.id === "lc:shipment_date") return `LC പ്രകാരമുള്ള അവസാന ഷിപ്പ്മെന്റ് തീയതിക്ക് ശേഷമാണ് ഷിപ്പ്മെന്റ്. ${c.message} LC ഭേദഗതി (amendment) ആവശ്യപ്പെടുക.`;
  if (c.id === "lc:description") return `Invoice-ലെ ചരക്കിന്റെ വിവരണം LC-യുമായി ഒത്തുപോകുന്നില്ല. ${c.message}`;
  if (c.id === "lc:amount") return `Invoice തുക LC തുകയേക്കാൾ കൂടുതലാണ്. ${c.message}`;
  if (c.id.startsWith("lc:port") || c.id === "lc:incoterms") return `രേഖകൾ LC നിബന്ധനകളുമായി ഒത്തുപോകുന്നില്ല. ${c.message}`;
  if (c.id.startsWith("lab:antibiotic")) return "സർട്ടിഫിക്കറ്റിൽ നിരോധിത ആന്റിബയോട്ടിക് കണ്ടെത്തിയിട്ടുണ്ട്. ഈ ലോട്ട് കയറ്റി അയക്കരുത്; ഫാം കണ്ടെത്തി വീണ്ടും പരിശോധിക്കുക.";
  if (c.id.startsWith("lab:eto")) return "Ethylene oxide അളവ് EU പരിധിയായ 0.1 mg/kg-ൽ കൂടുതലാണ്. ഈ ലോട്ട് EU-ലേക്ക് അയക്കരുത്.";
  if (c.id === "comp:required_docs") return `ആവശ്യമായ രേഖകൾ ഇല്ല. ${c.message}`;
  if (c.id === "comp:recommended_docs") return `ചില അനുബന്ധ രേഖകൾ അപ്‌ലോഡ് ചെയ്തിട്ടില്ല. ${c.message}`;
  return null;
}

const ML_UI = {
  fixesFor: "തിരുത്തേണ്ട കാര്യങ്ങൾ",
  shipment: "ഷിപ്പ്മെന്റ്",
  footer: "TallyTime പരിശോധനയിൽ കണ്ടെത്തിയത്. ഫയൽ ചെയ്യുന്നതിന് മുമ്പ് തിരുത്തുക.",
};


if __name__ == "__main__":
    import sys, os
    sys.path.insert(0, "..")
    sys.path.insert(0, ".")
    sys.path.insert(0, "lib")
    sys.path.insert(0, ".env/lib/python2.7/site-packages")
    os.environ["DJANGO_SETTINGS_MODULE"] = 'settings'

import datetime, lxml, os.path, re

bill_gpo_status_codes = {
    "ah": "Amendment",
    "ah2": "Amendment",
    "as": "Amendment",
    "as2": "Amendment",
    "ash": "Additional Sponsors",
    "sas": "Additional Sponsors",
    "sc": "Sponsor Change",
    "ath": "Resolution Agreed to",
    "ats": "Resolution Agreed to",
    "cdh": "Committee Discharged",
    "cds": "Committee Discharged",
    "cph": "Considered and Passed by the House",
    "cps": "Considered and Passed by the Senate",
    "eah": "Passed the House (Engrossed) with an Amendment",
    "eas": "Passed the Senate (Engrossed) with an Amendment",
    "eh": "Passed the House (Engrossed)",
    "ehr": "Passed the House (Engrossed)/Reprint",
    "eh_s": "Passed the House (Engrossed)/Star Print",
    "enr": "Passed Congress/Enrolled Bill",
    "renr": "Passed Congress/Re-enrolled",
    "es": "Passed the Senate (Engrossed)",
    "esr": "Passed the Senate (Engrossed)/Reprint",
    "es_s": "Passed the Senate (Engrossed)/Star Print",
    "fah": "Failed Amendment",
    "fps": "Failed Passage",
    "hdh": "Held at Desk in the House",
    "hds": "Held at Desk in the Senate",
    "ih": "Introduced",
    "ihr": "Introduced/Reprint",
    "ih_s": "Introduced/Star Print",
    "is": "Introduced",
    "isr": "Introduced/Reprint",
    "is_s": "Introduced/Star Print",
    "iph": "Indefinitely Postponed in the House",
    "ips": "Indefinitely Postponed in the Senate",
    "lth": "Laid on Table in the House",
    "lts": "Laid on Table in the Senate",
    "oph": "Ordered to be Printed",
    "ops": "Ordered to be Printed",
    "pch": "Placed on Calendar in the House",
    "pcs": "Placed on Calendar in the Senate",
    "pp": "Public Print",
    "rah": "Referred to House Committee (w/ Amendments)",
    "ras": "Referred to Senate Committee (w/ Amendments)",
    "rch": "Reference Change",
    "rcs": "Reference Change",
    "rdh": "Received by the House",
    "rds": "Received by the Senate",
    "reah": "Passed the House (Re-Engrossed) with an Amendment",
    "re": "Reprint of an Amendment",
    "res": "Passed the Senate (Re-Engrossed) with an Amendment",
    "rfh": "Referred to House Committee",
    "rfhr": "Referred to House Committee/Reprint",
    "rfh_s": "Referred to House Committee/Star Print",
    "rfs": "Referred to Senate Committee",
    "rfsr": "Referred to Senate Committee/Reprint",
    "rfs_s": "Referred to Senate Committee/Star Print",
    "rh": "Reported by House Committee",
    "rhr": "Reported by House Committee/Reprint",
    "rh_s": "Reported by House Committee/Star Print",
    "rs": "Reported by Senate Committee",
    "rsr": "Reported by Senate Committee/Reprint",
    "rs_s": "Reported by Senate Committee/Star Print",
    "rih": "Referral Instructions in the House",
    "ris": "Referral Instructions in the Senate",
    "rth": "Referred to House Committee",
    "rts": "Referred to Senate Committee",
    "s_p": "Star Print of an Amendment",
    "fph": "Failed Passage in the House",
    "fps": "Failed Passage in the Senate",
    }

def get_gpo_status_code_name(doc_version):
    # handle e.g. "eas2"
    digit_suffix = ""
    while len(doc_version) > 0 and doc_version[-1].isdigit():
        digit_suffix = doc_version[-1] + digit_suffix
        doc_version = doc_version[:-1]
    
    doc_version_name = bill_gpo_status_codes.get(doc_version, "Unknown Status (%s)" % doc_version)

    if digit_suffix: doc_version_name += " " + digit_suffix

    return doc_version_name
    
def get_current_version(bill):
    return load_bill_text(bill, None, mods_only=True)["doc_version"]
    
def load_bill_mods_metadata(fn):
    mods = lxml.etree.parse(fn)
    ns = { "mods": "http://www.loc.gov/mods/v3" }
    
    docdate = mods.xpath("string(mods:originInfo/mods:dateIssued)", namespaces=ns)
    gpo_url = "http://www.gpo.gov/fdsys/search/pagedetails.action?packageId=" + mods.xpath("string(mods:recordInfo/mods:recordIdentifier[@source='DGPO'])", namespaces=ns)
    #gpo_url = mods.xpath("string(mods:identifier[@type='uri'])", namespaces=ns)
    gpo_pdf_url = mods.xpath("string(mods:location/mods:url[@displayLabel='PDF rendition'])", namespaces=ns)
    doc_version = mods.xpath("string(mods:extension/mods:billVersion)", namespaces=ns)
    numpages = mods.xpath("string(mods:physicalDescription/mods:extent)", namespaces=ns)
    if numpages: numpages = re.sub(r" p\.$", " pages", numpages)
    
    docdate = datetime.date(*(int(d) for d in docdate.split("-")))
    doc_version_name = get_gpo_status_code_name(doc_version)

    # load a list of citations as marked up by GPO
    citations = []
    for cite in mods.xpath("//mods:identifier", namespaces=ns):
        if cite.get("type") == "USC citation":
            citations.append( parse_usc_citation(cite) )
        elif cite.get("type") == "Statute citation":
            citations.append({ "type": "statutes_at_large", "text": cite.text })
        elif cite.get("type") == "public law citation":
            try:
                congress_cite, slip_law_num = re.match(r"Public Law (\d+)-(\d+)$", cite.text).groups()
                citations.append({ "type": "slip_law", "text": cite.text, "congress": int(congress_cite), "number": int(slip_law_num) })
            except:
                citations.append({ "type": "unknown", "text": cite.text })
            
    return {
        "docdate": docdate,
        "gpo_url": gpo_url,
        "gpo_pdf_url": gpo_pdf_url,
        "doc_version": doc_version,
        "doc_version_name": doc_version_name,
        "numpages": numpages,
        "citations": citations,
    }

def parse_usc_citation(cite):
    m = re.match(r"(\d+)\s*U.S.C.(\s*App.)?\s*Chapter\s*(\S+)$", cite.text)
    if m:
        title_cite, title_app_cite, chapter_cite = m.groups()
        if title_app_cite: title_cite += "a"
        return { "type": "usc-chapter", "text": cite.text, "title": title_cite, "chapter": chapter_cite, "key" : "usc/chapter/" + title_cite + "/" + chapter_cite }
    
    m = re.match(r"(\d+\S*)\s*U.S.C.(\s*App.)?\s*([^\s(]+?)?\s*(\(.*|et ?seq\.?|note)?$", cite.text)
    if m:
        title_cite, title_app_cite, sec_cite, para_cite = m.groups()
        if title_app_cite: title_cite += "a"
        if para_cite and para_cite.strip() == "": para_cite = None
        
        # The citation may contain any number of dashes. At most one may indicate
        # a range, and the rest are dashes that appear within section numbers themselves.
        # Loop through all of the dashes and check if it splits the citation into two
        # valid section numbers (i.e. actually appears in the USC) that are also near
        # each other (same parent).
        #
        # A nice example is 16 U.S.C. 3839aa-8, where both "3839aa" and "8" are valid
        # sections but are far apart, so this does not indicate a range.
        #
        # Skip this if there is a paragraph in the citation --- that can't be appended
        # to a range.
        sec_dash_parts = sec_cite.split("-") if not para_cite else []
        for i in xrange(1, len(sec_dash_parts)):
            # Split the citation around the dash to check each half.
            sec_parts = ["-".join(sec_dash_parts[:i]),
                         "-".join(sec_dash_parts[i:])]
            from models import USCSection
            matched_secs = list(USCSection.objects.filter(citation__in = 
                [("usc/" + title_cite + "/" + sec_part) for sec_part in sec_parts]))
            if len(matched_secs) != 2: continue # one or the other was not a valid section number
            if matched_secs[0].parent_section_id != matched_secs[1].parent_section_id: continue # not nearby
            return { "type": "usc", "text": cite.text, "title": title_cite, "section": sec_parts[0], "paragraph": None, "range_to_section": sec_parts[1], "key" : "usc/" + title_cite + "/" + sec_parts[0] }
            
        # Not a range.
        return { "type": "usc-section", "text": cite.text, "title": title_cite, "section": sec_cite, "paragraph" : para_cite, "key" : "usc/" + title_cite + "/" + sec_cite }
        
    return { "type": "unknown", "text": cite.text }

def get_bill_text_metadata(bill, version):
    from bill.models import BillType # has to be here and not module-level to avoid cyclic dependency
    import glob, json

    bt = BillType.by_value(bill.bill_type).slug
    basename = "data/congress/%d/bills/%s/%s%d/text-versions" % (bill.congress, bt, bt, bill.number)
    
    if version == None:
        # Cycle through files to find most recent version by date.
        dat = None
        for versionfile in glob.glob(basename + "/*/data.json"):
            d = json.load(open(versionfile))
            if not dat or d["issued_on"] > dat["issued_on"]:
                dat = d
        if not dat: return None
    else:
        dat = json.load(open(basename + "/%s/data.json" % version))
        
    basename += "/" + dat["version_code"]

    bt2 = BillType.by_value(bill.bill_type).xml_code
    html_fn = "data/us/bills.text/%s/%s/%s%d%s.html" % (bill.congress, bt2, bt2, bill.number, dat["version_code"])

    if os.path.exists(basename + "/mods.xml"):
        dat["mods_file"] = basename + "/mods.xml"

    # get a plain text file if one exists
    if os.path.exists(basename + "/document.txt"):
        dat["text_file"] = basename + "/document.txt"
        dat["has_displayable_text"] = True

        for source in dat.get("sources", []):
            if source["source"] == "statutes":
                dat["text_file_source"] = "statutes"

    # get an HTML file if one exists
    if os.path.exists(html_fn):
        dat["html_file"] = html_fn
        dat["has_displayable_text"] = True

    # get an XML file if one exists
    if os.path.exists(basename + "/catoxml.xml"):
        dat["xml_file"] = basename + "/catoxml.xml"
        dat["has_displayable_text"] = True
        dat["xml_file_source"] = "cato-deepbills"
    elif os.path.exists(basename + "/document.xml"):
        dat["xml_file"] = basename + "/document.xml"
        dat["has_displayable_text"] = True

    thumb_fn = "data/us/bills.text/%s/%s/%s%d%s-thumb200.png" % (bill.congress, bt2, bt2, bill.number, dat["version_code"])
    if os.path.exists(thumb_fn):
        dat["thumbnail_path"] = thumb_fn
    
    return dat
        
def load_bill_text(bill, version, plain_text=False, mods_only=False):
    # Load bill text info from the Congress project data directory.
    # We have JSON files for metadata and plain text files mirrored from GPO
    # containing bill text (either from the Statutes at Large OCR'ed text
    # layers, or from GPO FDSys's BILLS collection).
    
    dat = get_bill_text_metadata(bill, version)
    if not dat:
        # No text is available.
        if plain_text:
            return "" # for indexing, just return empty string if no text is available
        raise IOError("Bill text is not available for this bill.")

    ret = {
        "bill_id": bill.id,
        "bill_name": bill.title,
        "has_displayable_text": dat.get("has_displayable_text"),
    }

    # Load basic metadata from a MODS file if one exists.
    if "mods_file" in dat:
        ret.update(load_bill_mods_metadata(dat["mods_file"]))

    # Otherwise fall back on using the text-versions data.json file. We may have
    # this for historical bills that we don't have a MODS file for.
    else:
        gpo_url = dat["urls"]["pdf"]

        m = re.match(r"http://www.gpo.gov/fdsys/pkg/(STATUTE-\d+)/pdf/(STATUTE-\d+-.*).pdf", gpo_url)
        if m:
            # TODO (but not needed right now): Docs from the BILLS collection.
            gpo_url = "http://www.gpo.gov/fdsys/granule/%s/%s/content-detail.html" % m.groups()

        ret.update({
            "docdate": datetime.date(*(int(d) for d in dat["issued_on"].split("-"))),
            "gpo_url": gpo_url,
            "gpo_pdf_url": dat["urls"]["pdf"],
            "doc_version": dat["version_code"],
            "doc_version_name": get_gpo_status_code_name(dat["version_code"]),
        })

    # Pass through some fields.
    for f in ('html_file', 'thumbnail_path'):
        if f in dat:
            ret[f] = dat[f]

    # If the caller only wants metadata, return it.
    if mods_only:
        return ret

    if "xml_file" in dat and not plain_text:
        # convert XML on the fly to HTML
        import lxml.html, congressxml
        ret.update({
            "text_html": lxml.html.tostring(congressxml.convert_xml(dat["xml_file"])),
            "source": dat.get("xml_file_source"),
        })

    elif "html_file" in dat and not plain_text:
        # This will be for bills around the 103rd-108th Congresses when
        # bill text is available from GPO but not in XML.
        ret.update({
            "text_html": open(dat["html_file"]).read().decode("utf8"),
        })

    elif "text_file" in dat:
        # bill text from the Statutes at Large, or when plain_text is True then from GPO

        bill_text_content = open(dat["text_file"]).read().decode("utf8")

        # In the GPO BILLS collection, there's gunk at the top and bottom that we'd
        # rather just remove: metadata in brackets at the top, and <all> at the end.
        # We remove it because it's not really useful when indexing.
        if bill_text_content:
            bill_text_content = re.sub(r"^\s*(\[[^\n]+\]\s*)*", "", bill_text_content)
            bill_text_content = re.sub(r"\s*<all>\s*$", "", bill_text_content)

        # Caller just wants the plain text?
        if plain_text:
            # replace form feeds (OCR'd layers only) with an indication of the page break
            return bill_text_content.replace(u"\u000C", "\n=============================================\n")
            
        # Return the text wrapped in <pre>, and replace form feeds with an <hr>.
        import cgi
        bill_text_content = "<pre>" + cgi.escape(bill_text_content) + "</pre>"
        bill_text_content = bill_text_content.replace(u"\u000C", "<hr>") # (OCR'd layers only)

        ret.update({
            "text_html": bill_text_content,
            "source": dat.get("text_file_source"),
        })


    return ret
    

def compare_xml_text(doc1, doc2, timelimit=10):
    # Compare the text of two XML documents, marking up each document with new
    # <span> tags. The documents are modified in place.
    
    def make_bytes(s):
        if type(s) != str:
            s = s.encode("utf8")
        else:
            pass # assume already utf8
        return s
    
    def serialize_document(doc):
        from StringIO import StringIO
        class State(object):
            pass
        state = State()
        state.text = StringIO()
        state.offsets = list()
        state.charcount = 0
        def append_text(text, node, texttype, state):
            if not text: return
            text = make_bytes(text)
            state.text.write(text)
            state.offsets.append([state.charcount, len(text), node, texttype])
            state.charcount += len(text)
        def recurse_on(node, state):
            # etree handles text oddly: node.text contains the text of the element, but if
            # the element has children then only the text up to its first child, and node.tail
            # contains the text after the element but before the next sibling. To iterate the
            # text in document order, we cannot use node.iter().
            append_text(node.text, node, 0, state) # 0 == .text
            for child in node:
                recurse_on(child, state)
            append_text(node.tail, node, 1, state) # 1 == .tail
        recurse_on(doc.getroot(), state)
        state.text = state.text.getvalue()
        return state
        
    doc1data = serialize_document(doc1)
    doc2data = serialize_document(doc2)
    
    def simplify_diff(diff_iter):
        # Simplify the diff by collapsing any regions with more changes than
        # similarities, so that small unchanged regions appear within the larger
        # set of changes (as changes, not as similarities).
        prev = []
        for op, length in diff_iter:
            if len(prev) < 2:
                prev.append( (op, length) )
            else:
                # If the op two hunks ago is the same as the current hunk and
                # the total lengths of two hunks ago and the current is creater
                # than the length of the hunk in the middle...
                if op in ('-', '+') and prev[0][0] == op and prev[1][0] == '=' \
                    and prev[0][1] + length > (prev[1][1]-1)**1.4:
                    prev.append( (op, prev[0][1] + prev[1][1] + length) )
                    prev.append( ('-' if op == '+' else '+', prev[1][1]) )
                    prev.pop(0)
                    prev.pop(0)
                    
                # If the two hunks differ in op, combine them a different way.
                elif op in ('-', '+') and prev[0][0] in ('-', '+') and prev[1][0] == '=' \
                    and prev[0][1] + length > (prev[1][1]-1)**1.4:
                    prev.append( (prev[0][0], prev[0][1] + prev[1][1]) )
                    prev.append( (op, prev[1][1] + length) )
                    prev.pop(0)
                    prev.pop(0)
                
                else:
                    yield prev.pop(0)
                    prev.append( (op, length) )
        for p in prev:
            yield p
    
    def reformat_diff(diff_iter):
        # Re-format the operations of the diffs to indicate the byte
        # offsets on the left and right.
        left_pos = 0
        right_pos = 0
        for op, length in diff_iter:
            left_len = length if op in ("-", "=") else 0
            right_len = length if op in ("+", "=") else 0
            yield (op, left_pos, left_len, right_pos, right_len)
            left_pos += left_len
            right_pos += right_len
           
    def slice_bytes(text, start, end):
        # Return the range [start:length] from the byte-representation of
        # the text string, returning unicode. If text is unicode, convert to
        # bytes, take the slice, and then convert back from UTF8 as best as
        # possible since we may have messed up the UTF8 encoding.
       return make_bytes(text)[start:end].decode("utf8", "replace")
           
    def mark_text(doc, offsets, pos, length, mode):
       # Wrap the text in doc at position pos and of byte length length
       # with a <span>, and set the class to mode.
       def make_wrapper(label=None):
           wrapper_node = lxml.etree.Element('span')
           wrapper_node.set('class', mode)
           #if label: wrapper_node.set('make_wrapper_label', label)
           return wrapper_node
       for i, (off, offlen, offnode, offtype) in enumerate(offsets):
           # Does the change intersect this span?
           if pos >= off+offlen or pos+length <= off: continue
           
           if pos == off and length >= offlen:
               # The text to mark is the whole part of this span,
               # plus possibly some more.
               if offtype == 0:
                   # It is the node's .text, meaning replace the text
                   # that exists up to the node's first child.
                   w = make_wrapper("A")
                   w.text = offnode.text
                   offnode.text = ""
                   offnode.insert(0, w)
               else:
                   # It is the node's .tail, meaning replace the text
                   # that exists after the element and before the next
                   # sibling.
                   w = make_wrapper("B")
                   offtail = offnode.tail # see below
                   offnode.addnext(w)
                   w.text = offtail
                   w.tail = None
                   offnode.tail = ""
           elif pos == off and length < offlen:
               # The text to mark starts here but ends early.
               if offtype == 0:
                   w = make_wrapper("C")
                   offnode.insert(0, w)
                   w.text = slice_bytes(offnode.text, 0, length)
                   w.set("txt", slice_bytes(offnode.text, 0, length))
                   w.tail = slice_bytes(offnode.text, length, offlen)
                   offnode.text = ""
               else:
                   w = make_wrapper("D")
                   offtail = offnode.tail # get it early to avoid any automatic space normalization
                   offnode.addnext(w) # add it early for the same reason
                   w.text = slice_bytes(offtail, 0, length)
                   w.tail = slice_bytes(offtail, length, offlen)
                   offnode.tail = ""
               # After this point we may come back to edit more text in this
               # node after this point. However, what was in this node at offset
               # x is now in the tail of the new wrapper node at position x-length.
               offsets[i] = (off+length, offlen-length, w, 1)
           elif pos > off and pos+length >= off+offlen:
               # The text to mark starts part way into this span and ends
               # at the end (or beyond).
               if offtype == 0:
                   w = make_wrapper("E")
                   offnode.insert(0, w)
                   w.text = slice_bytes(offnode.text, pos-off, offlen)
                   offnode.text = slice_bytes(offnode.text, 0, pos-off)
               else:
                   w = make_wrapper("F")
                   offtail = offnode.tail # see above
                   offnode.addnext(w) # see above
                   w.text = slice_bytes(offtail, pos-off, offlen)
                   w.tail = None
                   offnode.tail = slice_bytes(offtail, 0, pos-off)
           elif pos > off and pos+length < off+offlen:
               # The text to mark starts part way into this span and ends
               # early.
               if offtype == 0:
                   w = make_wrapper("G")
                   offnode.insert(0, w)
                   w.text = slice_bytes(offnode.text, pos-off, (pos-off)+length)
                   w.tail = slice_bytes(offnode.text, (pos-off)+length, offlen)
                   offnode.text = slice_bytes(offnode.text, 0, pos-off)
               else:
                   #if len(make_bytes(offnode.tail)) != offlen: raise Exception(str(len(make_bytes(offnode.tail))) + "/" + str(offlen) + "/" + lxml.etree.tostring(offnode))
                   w = make_wrapper("H")
                   offtail = offnode.tail # see above
                   offnode.addnext(w) # see above
                   w.text = slice_bytes(offtail, pos-off, (pos-off)+length)
                   w.tail = slice_bytes(offtail, (pos-off)+length, offlen)
                   offnode.tail = slice_bytes(offtail, 0, pos-off)
               # After this point we may come back to edit more text in this
               # node after this point. However, what was in this node at offset
               # x is now in the tail of the new wrapper node at position x-length.
               offsets[i] = (off+(pos-off)+length, offlen-(pos-off)-length, w, 1)
           else:
               raise Exception()
           
           if pos+length > off+offlen:
               d = off+offlen - pos
               pos += d
               length -= d
               if length <= 0: return
           
    def get_bounding_nodes(pos, length, offsets):
       nodes = []
       for off, offlen, offnode, offtype in offsets:
           if off <= pos < off+offlen:
               nodes.append(offnode)
           if off <= pos+length < off+offlen:
               nodes.append(offnode)
       if len(nodes) == 0: return None
       return nodes[0], nodes[-1]
    def mark_correspondence(leftnode, rightnode, idx, ab):
        if not leftnode.get("id"): leftnode.set("id", "left_%d%s" % (idx, ab))
        if not rightnode.get("id"): rightnode.set("id", "right_%d%s" % (idx, ab))
        leftnode.set("cw_" + ab, rightnode.get("id"))
        rightnode.set("cw_" + ab, leftnode.get("id"))
           
    import diff_match_patch
    diff = diff_match_patch.diff(doc1data.text, doc2data.text, timelimit=timelimit)
    diff = reformat_diff(simplify_diff(diff))
    idx = 0
    for op, left_pos, left_len, right_pos, right_len in diff:
        idx += 1
        left_nodes = get_bounding_nodes(left_pos, left_len, doc1data.offsets)
        right_nodes = get_bounding_nodes(right_pos, right_len, doc2data.offsets)
        if left_nodes and right_nodes:
            mark_correspondence(left_nodes[0], right_nodes[0], idx, "top")
            mark_correspondence(left_nodes[1], right_nodes[1], idx, "bot")
        
        if op == "=" and doc1data.text[left_pos:left_pos+left_len] == doc2data.text[right_pos:right_pos+right_len]: continue
        if left_len > 0: mark_text(doc1, doc1data.offsets, left_pos, left_len, "del" if right_len == 0 else "change")
        if right_len > 0: mark_text(doc2, doc2data.offsets, right_pos, right_len, "ins" if left_len == 0 else "change")
    
    return doc1, doc2
    
if __name__ == "__main__":
    from bill.models import Bill, BillType
    load_bill_text(Bill.objects.get(congress=112, bill_type=BillType.house_bill, number=9), None)
    #doc1 = lxml.etree.parse("data/us/bills.text/112/h/h3606ih.html")
    #doc2 = lxml.etree.parse("data/us/bills.text/112/h/h3606eh.html")
    #compare_xml_text(doc1, doc2)
    #print lxml.etree.tostring(doc2)

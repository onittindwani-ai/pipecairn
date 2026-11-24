"""Word patterns for the offline stand in reader (rules, NOT a language model).

Written from general knowledge of how people answer a sales email: refusals, "ask me later", "talk to someone else",
yes and scheduling phrases, questions, plus a few common phrases in other languages. Texts are normalised first
(reply_text.normalize: lower case, straight quotes, "don't" opened to "do not"), so these patterns do not repeat contractions.
None of these patterns was taken from an evaluation set.
"""

from __future__ import annotations

import re

MONTH = r"(january|february|march|april|may|june|july|august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sept?|oct|nov|dec)"
DAY = r"(monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|tues|wed|thu|thur|thurs|fri)"
SEASON = r"(spring|summer|fall|autumn|winter|holidays?|new year|year end|year-end|end of (the )?(year|month|quarter)|q[1-4]|h[12])"

# "not interested", "no need", "we pass": a refusal. Whether it is a stop or a "later" depends on a time word (see NOT_NOW).
REFUSAL = re.compile(
    r"\b(not|no|never|hardly)\b( \w+){0,3}? (interested|interest|need|needs|want|looking|useful|helpful|keen|a fit|for us|for me|something we|what we|required|relevant|applicable)\b|"
    r"\bno,? thanks?\b|\bno thank you\b|\bnot for us\b|\bwe pass\b|\bi pass\b|\bpass on (this|that|it)\b|\bdecline\b|\bnot at all\b|\bwe are (good|fine|covered|set)\b|\bnot a fit\b|"
    r"\bnicht interessiert\b|\bkein interesse\b|\bpas int[ée]ress[ée]\b|\bno (me )?interesa\b|\bn[aã]o (tenho|temos) interesse\b|\bnon (siamo |sono )?interessat\w+\b|\bgeen interesse\b|\bnie jestem zainteresowan\w+\b|\bilgilenmiyorum\b|\bj[aä]g (är|ar) inte intresserad\b|\bdilchaspi nahi\b|\binterested nahi\b", re.I)

NOT_NOW = re.compile(
    r"\b(not|no) (right |just )?(now|yet|today)\b|\bnot at (this|the) (time|moment|stage|point)\b|\bfor now\b|"
    r"\b(currently|presently|right now|at the moment) (busy|swamped|full|booked|overloaded|stretched|focused|under|working|in the middle|mid|tied|have no|have a|using|with)\b|\bin the middle of\b|\bbandwidth\b|\bno capacity\b|\bat capacity\b|\btoo busy\b|\btied up\b|\bother priorit\w+|"
    r"\bon hold\b|\bhold off\b|\bpostpone\w*|\bdefer\w*|\bpause[ds]?\b|\bpaused\b|\bnot (a )?(good|great|ideal|right|best) (time|moment)\b|\b(timing|time) (is|is not|isn't) (right|good|great|ideal)\b|"
    r"\b(maybe|perhaps|possibly|probably) (later|next|in|after|then|at some point|someday)\b|\b(later|another time|down the (road|line)|some other time|sometime|in the future|at a later date|further down)\b|"
    rf"\b(check|come|reach|circle|get|touch|ask|try|call|contact|ping|email|write|follow|talk|speak|revisit|reconnect|reconsider|look|hear|hearing)\w*( \w+){{0,3}}? (again|later|then|in (a|an|two|three|four|five|six|a few|a couple of|\d+) (months?|quarters?|years?)|in (early|mid|late|{MONTH}|{SEASON})|{MONTH}|{SEASON})\b|"
    rf"\b(after|until|once|when|during) (the )?(holidays?|summer|season|audit|move|renovation|launch|merger|quarter|year|new year|tax|busy|peak|{MONTH}|{SEASON}|we (have|are|get|finish|complete|close|move|settle))\b|"
    rf"\b(next|this coming) (quarter|year|season|{MONTH}|{SEASON})\b|\b(budget|fiscal|planning|contract|renewal|lease) (cycle|year|freeze|season|period|ends?|is up|expires?|runs? until|through)\b|"
    r"\b(contract|agreement|lease|subscription|renewal) (is |runs |ends |expires |locked |signed )?(until|through|till|for (the )?(next|another))|\blocked in\b|\balready (have|use|using|work|signed|partner|with)\w*|\bhave (a|an) (provider|vendor|supplier|arrangement|contract|system)\b|"
    r"\bnot (a |our )?(priority|focus)\b|\bnot (this|that) (quarter|year|month|season|week)\b|\bbefore (the )?(summer|spring|fall|autumn|winter|holidays?|new year|q[1-4])\b|\b(once|when|after) (that|this|it|everything) (is|are|has been|gets?) (done|over|finished|complete|completed|settled|behind us|sorted)\b|\bnot budgeted\b|\bno budget\b|\bbudget (is )?(tight|frozen|exhausted|committed)\b|\bnext (week|month) (is|will be) (busy|hectic|full)\b", re.I)

WRONG = re.compile(
    r"\b(wrong|incorrect|different) (person|address|email|e-mail|number|contact|department|company|recipient|office|inbox)\b|\bnot the (right|correct|best|proper|appropriate|relevant) (person|contact|one|place|address|team|department|recipient|fit person)\b|\bnot (me|my (role|department|job|area|call|decision|remit|responsibility|side|field|team))\b|"
    r"\b(no longer|not) (work|works|working|employed|with|at|part of|in charge|responsible|involved)\b|\b(left|leaving|quit|resigned from|retired from|moved on from) (the |this |our )?(company|firm|practice|organi[sz]ation|business|clinic|team|role|position|job)\b|\bhas (left|retired|moved on|resigned)\b|\bsince (left|retired)\b|\bretired\b|\bpassed away\b|\bdeceased\b|"
    r"\b(i|we) (am|are) not (the|a|an|involved|in charge|responsible|authori[sz]ed|able to decide)\b|\bnot involved\b|\babove my (pay|level|grade)\b|\bdecision[- ]?makers?\b|\bi do not (make|decide|handle|manage|deal|own|run|oversee|work)\b|\bdoes not work here\b|\bno one (here )?(by that|with that) name\b|\bnobody (here|by that)\b|\bunknown (here|to us)\b|"
    r"\b(better|best) (person|contact|fit|placed|suited|address|point of contact)\b|\b(talk|speak|write|email|contact|reach out|get in touch|connect|go|check|ask|reach)\w*( \w+)? (to|with)( our| my| the| a)? (?!me\b|us\b)[\w.\-]+\b[^.\n]{0,40}\b(instead|who|he|she|they|handles?|runs?|manages?|in charge|responsible|decides?|better)\b|\binstead\b|"
    r"\b(contact|email|write to|reach|ask for|speak to|talk to|call|try)\b(?! me\b| us\b)[^.\n@]{0,40}\b(at|on) [\w.+\-]+@|\b(is|are) (the one|in charge|responsible|who you want|the person|the right|the best)\b|"
    r"\b(he|she|they|someone|somebody|which|that team|that department|accounts|finance|hr|it|marketing|procurement|purchasing) (handles?|handled|manages?|runs?|looks after|oversees|owns|takes care)\b|\b(forward(ed)?|pass(ed|ing)?|direct(ed)?|refer(red)?|redirect(ed)?|sent) (this|it|your (e-?mail|message))( on)? to\b|\bi (have )?looped\b|"
    r"\bowner is\b|\bnot (to )?me\b|\bnot mine\b|\bwe have (a|an) (separate|dedicated|different|specific|central) (\w+ )?(team|person|department|manager|office|desk)\b|\b(i will|i'll|let me|i can) (pass|forward|send|share|hand|route)\b[^.\n]{0,30}\b(along|on|over)\b|\b(contact|email|ask|speak|talk|write|reach)\w*( out)? (to |with |for )?(the )?(owner|manager|director|principal|partner|founder|ceo|cfo|cto|boss|head|lead|supervisor|hr|finance|accounts|billing|procurement|purchasing|administrator|receptionist|front desk)\b|"
    r"\b(should|could|can|might|may|best|better|recommend|suggest)\b[^.\n]{0,25}\b(reach out|speak|talk|contact|ask|email|write|try|get in touch|connect|approach)\w*( \w+)? (to|with)( our| my| the| a)? (?!me\b|us\b)[\w.\-]+|\bpractice manager\b|\boffice manager\b|\bhead office\b|\bheadquarters\b|\bparent company\b|"
    r"\bfalsche (person|adresse)\b|\bnicht (der|die) richtige\b|\bn'?est pas la bonne personne\b|\bmauvaise (personne|adresse)\b|\bpersona equivocada\b|\bno soy (la persona|yo)\b|\bpessoa errada\b|\bpersona sbagliata\b|\bverkeerde (persoon|adres)\b|\bniewłaściw\w+ osob\w+\b|\byanl[ıi][sş] ki[sş]i\b|\bgalat (insaan|jagah|address)\b", re.I)

# Words that mean "yes, let us talk" or "send me the details". Scheduling words count as interest.
STRONG = re.compile(
    r"\b(yes|yeah|yep|yup|sure|absolutely|definitely|certainly|of course|okay|ok|please do|go ahead|go for it|let us do it|let us go|count (me|us) in|i am in|we are in|sign (me|us) up)\b[^.?!\n]{0,40}\b(send|share|call|talk|chat|meet|schedule|book|set up|time|times|slot|slots|demo|proposal|pricing|quote|info|details|link|calendar|available|free|works?)\b|"
    r"\b(i|we) (would|will|do) (like|love|want|need|welcome|appreciate|be glad|be happy|be keen)( to)?\b|\b(happy|glad|keen|eager|excited|ready|willing|open|delighted|pleased) to\b|\bsounds (good|great|interesting|useful|promising|like a plan|intriguing|helpful|exactly)\b|\bworks for (me|us)\b|"
    r"\b(can|could|shall|may|should|would) (we|you|i) (ring|phone|text|come|show|demo|put|give|email|send|call|talk|chat|meet|speak|schedule|book|set up|jump|hop|get on|have a|arrange|catch up|connect|discuss|do|try|start|get started|walk)\w*\b|\blet us (talk|chat|meet|speak|connect|schedule|set|book|try|start|go|hop|jump|discuss|catch up|arrange|get|do|move)\b|"
    r"\b(send|share|forward|email|text|give|show) (me|us|over)( the| your| a| some| more| further| any| all)?( \w+)? ?(info|information|details|brochure|pricing|price|prices|proposal|quote|deck|times|slots|availability|link|options|case stud\w+|examples?|materials?|numbers|rates|terms|agreement|contract|overview|samples?|one-pager)\b|"
    r"\bwhat (times?|days?|slots?|dates?)\b|\bwhen (are|is|can|could|would) (you|we|your team)\b|\b(i|we) (am|are) (free|available|around|open|good|ok|okay)\b|\b(free|available|open|good) (on|at|this|next|tomorrow|today|tonight|after|before|from|between|early|late|any|anytime)\b|"
    rf"\b{DAY}\b|\b(tomorrow|today|tonight|this (week|afternoon|morning|evening)|next week|anytime|any time)\b[^.?!\n]{{0,30}}\b(call|talk|chat|meet|works?|free|available|good|time)\b|\bbook (a|the|me|us|in|it)\b|\bschedule (a|the|me|us|something|it)\b|\b(call|ring|phone|text|whatsapp|ping) (me|us)\b|\bgive (me|us) a (call|ring|buzz|shout)\b|\breach (me|us) (at|on)\b|"
    r"\b(my|our) (calendar|diary|schedule|number|mobile|cell|direct line|phone|availability)\b|\bhow (do|can) (i|we) (get started|sign up|start|begin|proceed|move forward|buy|order|join|book)\b|\b(interested|intrigued|curious|tempted|keen|eager|excited|enthusiastic)\b|\bwalk[- ]?through\b|\bwalk (me|us) through\b|\btell (me|us) more\b|\bmore (info|information|details)\b|\blearn(ing)? more\b|\bworth (a|the|having|exploring|discussing|trying|looking)\b|"
    r"\bja,? (gerne|bitte|klar)\b|\bgerne\b|\binteressant\b|\bruf(en)? sie\b|\boui,? (volontiers|avec plaisir|bien sûr)\b|\bint[ée]ress[ée]\b|\bvolontiers\b|\bme interesa\b|\bs[ií],? (por favor|claro|me gustaría)\b|\bmás información\b|\bestou interessad\w+\b|\bquero saber mais\b|\bsim,? (por favor|claro)\b|\bmi interessa\b|\bsono interessat\w+\b|\bvolentieri\b|\bgeïnteresseerd\b|\bgraag\b|\bja,? (graag|zeker)\b|\bzainteresowan\w+\b|\bilgileniyorum\b|\bintresserad\b|\bbilkul\b|\bzaroor\b|\bhaan\b", re.I)

SCHEDULING_QUESTION = re.compile(
    rf"\b(what|which) (times?|days?|slots?|dates?)\b[^?.\n]*\?|\bwhen (can|could|are|would|is)\b[^?.\n]*\?|\b(does|would|will|is|are|do)\b[^?.\n]{{0,60}}\b(\d|{DAY}|tomorrow|today|morning|afternoon|evening|week|noon|pm|am)\b[^?.\n]{{0,30}}\b(work|ok|okay|good|fine|suit\w*|convenient)\b[^?.\n]*\?|"
    r"\b(does|would|will|is|do) (that|then) work\b[^?.\n]*\?|\bhow about\b[^?.\n]*\?|\bshall we\b[^?.\n]*\?|\b(can|could|would|will) (we|you) (please )?((talk|chat|meet|speak|schedule|book|set|jump|hop|get on|ring|call|phone|text|arrange|come)\b|(send|share|put|give|show|walk|email|forward|demo) (me|us|over)\b)[^?.\n]*\?", re.I)

QUESTION = re.compile(
    r"\b(what|which) (times?|days?|slots?|dates?)\b[^?.\n]*\?|\bwhen (can|could|are|would|is)\b[^?.\n]*\?|\b(does|would|will|is|are|do) [^?.\n]{0,40}\b(work|ok|okay|good|fine|suit\w*|convenient)\b[^?.\n]*\?|\bhow about\b[^?.\n]*\?|\bshall we\b[^?.\n]*\?|\bcan we (talk|chat|meet|speak|schedule|book|set|jump|hop|get on)\b[^?.\n]*\?", re.I)

QUESTION = re.compile(
    r"\b(what|which|who|whom|whose|where|why|how|when)\b|\b(do|does|did|can|could|would|will|is|are|was|were|have|has|should|may|might) (you|your|it|this|that|there|we|i|the|they|these)\b|\bwondering\b|\bexplain\b|\bclarify\b|\bcurious (how|what|if|about|whether)\b|\b(any|more|further) (info|information|details|questions?)\b|\bnot sure\b|\bunclear\b|\b(price|prices|pricing|cost|costs|fee|fees|rate|rates)\b|\bcould you (tell|explain|share|clarify|confirm|say|let)\b|\bwould you (mind|be able|tell|explain|share|clarify|confirm)\b|\bplease (tell|explain|clarify|confirm|advise|let me know)\b|"
    r"\bwas (ist|macht|kostet)\b|\bwie (viel|funktioniert)\b|\bqu[ée] (es|hace|cuesta)\b|\bcu[aá]nto\b|\bcomment\b|\bcombien\b|\bquanto\b|\bwat (is|kost|doet)\b|\bhoeveel\b|\bile kosztuje\b|\bne kadar\b|\bkya (hai|karta)\b|\bkitna\b", re.I)

# A named person the reply points to ("Speak to Chris"). Case sensitive on purpose: the capital letter says it is a name.
# The greeting name (the person we wrote to) is removed by the caller before this runs.
NAMED_REFERRAL = re.compile(
    r"(?:^|[.!?,;]\s*|\b)(?:[Ss]peak|[Tt]alk|[Ww]rite|[Rr]each out|[Gg]et in touch|[Aa]sk|[Tt]ry|[Cc]ontact|[Ee]mail|[Cc]all|[Ss]ee|[Rr]efer(?: you)?|[Ff]orward(?: this)?|[Dd]irect(?: this)?)\w*\s+(?:to |with |for )?"
    r"(?:Mr\.?|Mrs\.?|Ms\.?|Dr\.?|Prof\.?)?\s*(?!(?:Me|Us|You|Our|My|The|This|That|Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday|January|February|March|April|May|June|July|August|September|October|November|December)\b)[A-Z][a-z]{2,}")

# Plain statements of interest or enthusiasm. These win even when the reply also asks a question.
WARM = re.compile(
    r"\b(i am|we are|i'm|my team is|our team is|sounds?|looks?|seems?) (very |really |quite |pretty |so |super )?(keen|interested|intrigued|excited|enthusiastic|promising|good|great|interesting|useful|helpful|intriguing|like a fit)\b|\b(i|we) (would|will) (love|like) to (see|hear|learn|know|try|talk|chat|meet|discuss|get)\b", re.I)

__description__ = \
"""
Code for parsing slidemachine style markdown and generating html.
"""
__author__ = "Michael J. Harms"
__date__ = "2018-05-09"
__usage__ = ""

from . import processors

import mistune
import sys, re, copy, os, json, shutil

class SlideMachineError(Exception):
    """
    General error class for this module.
    """
    pass

class Slide:
    """
    Hold a representation of a single markdown slide.  This may consist of
    multiple sub-slides generated by processors.
    """

    def __init__(self,slide_lines):
        """
        slide_lines: list of lines that constitute a slide.
        """

        self._slide_lines = copy.deepcopy(slide_lines)
        self._sub_slides = [copy.deepcopy(self._slide_lines)]

        # Whether or not to override the default transition with "none".
        # Gets set to "True" when the slide expands into multiple sub-slides
        self._override_transition = False

    def apply(self,processor):
        """
        Apply an instance of a subclass of Processor to each line in the slide.
        """

        processor_expanded_slide = False

        new_sub_slides = []
        for sub_slide in self._sub_slides:

            expanded_line = -1

            new_lines = []
            for i, line in enumerate(sub_slide):

                # Process the line.  If the processor does nothing, it returns the
                # input line.  If it did something somewhat interesting, the line will
                # be slightly different than input.  If it interprets the input line
                # as creating multiple other slidies, it will return a tuple of lines.
                new_line = processor.process(line)

                new_lines.append(new_line)

                # new_line will be a tuple if the processor has broken the one initial
                # slide into multiple sub_slides
                if type(new_line) is tuple:

                    if expanded_line >= 0:
                        err =  "Error in {}.".format(processor)
                        err += "A slide cannot contain more than one tag of the same "
                        err += "type that expand into multiple slides.\n\n"
                        err += "Offending slide:\n\n"
                        err += "".join(self._slide_lines)

                        raise SlideMachineError(err)

                    processor_expanded_slide = True
                    expanded_line = i

            # If the slide was expanded, append multiple new sub_slides
            if expanded_line >= 0:

                # Break slide in half at the expanded line
                first_half = new_lines[:expanded_line]
                second_half = new_lines[(expanded_line+1):]

                # Now build a new sub_slide for each rendered file
                for i, t in enumerate(new_lines[expanded_line]):
                    out = copy.deepcopy(first_half)
                    out.append(t)
                    out.extend(second_half)

                    new_sub_slides.append(out)

            # No expansion, just record the lines as a single slide
            else:
                new_sub_slides.append(new_lines)

        # Record the final result in the sub_slides attribute
        self._sub_slides = copy.deepcopy(new_sub_slides)

        if processor_expanded_slide:
            self._override_transition = True

    @property
    def markdown(self):
        return "".join(self._original_slide_lines)


    @property
    def html(self):
        """
        Return the slide (or collection of sub slides) as reveal.js
        compatible html.
        """

        markdown = mistune.Markdown()

        # Construct html, with each subslide separted by <section>
        # html breaks that can be read by reveal.js
        out = []
        for i, s in enumerate(self._sub_slides):

            if self._override_transition:
                start = "<section data-transition=\"none\">\n"
            else:
                start = "<section>\n"

            middle = markdown("".join(s))

            middle = middle.split("\n")
            middle = "".join(["  {:}\n".format(m) for m in middle])
            middle = middle.rstrip()

            end = "\n</section>\n\n"

            out.append("{}{}{}".format(start,middle,end))

        return "".join(out)

class SlideMachine:
    """
    Main class that parses markdown, runs processors, and generates final
    html.
    """

    def __init__(self,md_file,json_file=None,target_dir=None,force=False):
        """
        md_file: markdown file to be processed
        json_file: json file with configuration information.  If None, a
                   default json file is used.
        target_directory: if specified, single output directory for all media.
                          overrides whatever is in json
        force: overwrite existing files and target directories.
        """

        self._md_file = md_file
        self._json_file = json_file
        self._target_dir = target_dir
        self._force = force

        self._slide_break = ">>>"

        self._load_json()
        self._read_md_file()

    def _load_json(self):
        """
        Load a json file containing information about which processors to use
        and their options.
        """

        # If no json file is specified, use the one that ships with the
        # package
        if self._json_file is None:
            current_dir = os.path.dirname(os.path.realpath(__file__))
            self._json_file = os.path.join(current_dir,"config.json")

        # Read json file
        json_input = json.load(open(self._json_file,'r'))

        # Try to parse a "processors" key, which indicates which processors
        # to use
        self._processors = []
        try:

            avail_processors = json_input["processors"]

            # In the processors dict, keys should be names of processor
            # classes, values should be dict of keywords to pass when
            # initializing the processor
            for k in avail_processors.keys():

                # Initialize an instance of the class
                p = getattr(processors,k)(**avail_processors[k])

                # If a target dir is specified on the command line, override
                # what's in the json
                if self._target_dir is not None:
                    p.target_dir = self._target_dir

                # append the processor to the processor
                self._processors.append(p)

            # Remove the special processors key from the
            json_input.pop("processors")
        except KeyError:
            pass

        # get list of output directories and create them
        target_dirs = set([p.target_dir for p in self._processors])
        for d in target_dirs:
            if os.path.isdir(d):
                if self._force:
                    shutil.rmtree(d)
                else:
                    err = "\n\nTarget directory {} already exists.\n".format(d)
                    err += "Use --force to overwrite.\n\n"
                    raise IOError(err)
            os.mkdir(d)

        # Remaining keys should set attributes of this class
        for key in json_input:
            new_key = "_{}".format(key)
            setattr(self,new_key,json_input[key])

    def _read_md_file(self):
        """
        Read a markdown file, looking for a pattern that breaks markdown
        into slides.  Populates self._slides with a Slide instance for
        each slide.
        """

        # Read contents of md file as a set of lines
        try:
            f = open(self._md_file,'r')
            self._md_file_content = f.readlines()
            f.close()
        except AttributeError:
            err = "No markdown file specified.\n"
            raise ValueError(err)

        # pattern for slide break
        slide_break = re.compile(self._slide_break)

        # Break markdown into individual slides
        self._slides = []
        slide_content = []
        for line in self._md_file_content:

            if slide_break.search(line):
                self._slides.append(Slide(slide_content))
                slide_content = []
            else:
                slide_content.append(line)
        self._slides.append(Slide(slide_content))


    def _merge_with_reveal_file(self,reveal_file):
        """
        reveal_file: an html_file with a tag that has has the slides
        class.

        Returns the current html constructed from the markdown inserted
        in the "slides" div.
        """

        # Read in a reveal html file, breaking at first tag with the attribute
        # class="slides".  Populate reveal_top and reveal_bottom.
        # Slide content will be inserted between these blocks.

        search_pattern = re.compile("class=\"slides\"")

        filling_top = True
        top = []
        bottom = []
        with open(reveal_file,"r") as lines:
            for l in lines:

                if filling_top:
                    m = search_pattern.search(l)
                    if m:

                        attrib_end = m.end()
                        end_of_tag = re.search(">",l[attrib_end:]).end()

                        break_index = attrib_end + end_of_tag + 1
                        with_top = l[:(break_index-1)]

                        try:
                            with_bottom = l[(break_index-1):]
                        except IndexError:
                            with_bottom = ""

                        indent = (len(l) - len(l.lstrip()) + 2)*" "

                        top.append(with_top)
                        top.append("\n\n")

                        bottom.append("\n")
                        bottom.append((len(l) - len(l.strip()))*" ")
                        bottom.append(with_bottom)

                        filling_top = False


                        continue
                    else:
                        top.append(l)
                else:
                    bottom.append(l)

        reveal_top = "".join(top)
        reveal_bottom = "".join(bottom)

        # Add appropriate indentation
        html = self._html.split("\n")
        html = "\n".join(["{}{}".format(indent,h) for h in html])

        out = "{}{}{}".format(reveal_top,html,reveal_bottom)

        return out

    def process(self,output_file,reveal_html_file=None):
        """
        Generate html and images from markdown file.  Write out images to
        self._img_dir

        output_file: html file to write results
        reveal_html_file: html file with a class="slides" element that the
                          slides will be pasted in to.
        """

        # Make sure the output file does not already exist
        if os.path.isfile(output_file):
            if self._force:
                os.remove(output_file)
            else:
                err = "\n\nOutput file {} exists.\n\n".format(output_file)
                err += "Use --force to overwrite."
                raise IOError(err)

        # Apply processors
        for processor in self._processors:
            for slide in self._slides:
                slide.apply(processor)

        # Grab slide html
        html = []
        for slide in self._slides:
            html.append(slide.html)

        # Make final html for object
        self._html = "".join(html)

        # If a reveal html file is given, merge the new slides output
        # with that.
        if reveal_html_file is not None:
            out = self._merge_with_reveal_file(reveal_html_file)
        else:
            out = self.html

        # Write out output
        f = open(output_file,'w')
        f.write(out)
        f.close()

    @property
    def markdown(self):
        """
        Input markdown.
        """

        return "".join(self._md_file_content)

    @property
    def html(self):
        """
        Final html.
        """

        return self._html

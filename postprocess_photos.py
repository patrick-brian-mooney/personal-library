#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""

The postprocess-photos.py script performs the kind of postprocessing work that
needs to happen when I move photos to my hard drive. It processes an entire
directory at a time; just invoke it by typing

    ./postprocess-photos.py

in the directory that needs to be processed.

Currently, it performs the following tasks:
    1. Empties out the folder's .thumbnails directory if it has files, creates
       it if it doesn't exist, and locks it down by making it non-writable.
    2. Auto-renames all photos in the current directory, then writes a file,
       file_names.csv, indicating what the original name of each renamed file
       was. Files are renamed so that their new names encode the date and time
       when they were taken, based on the EXIF info or existing filename.
    3. Keeps track of the original and new names in doing so, and creates a
       record of the mapping between old and new names in a file it calls
       file_names.csv.
    4. Auto-rotates all photos in the current directory by calling exiftran.
    5. If any .SH files are found in the directory being processed, it assumes
       they are Bash scripts that call enfuse, possibly preceded by a call to
       align_image_stack (and are the product of automatic exposure bracketing
       by Magic Lantern, which is the only way that .SH files ever wind up on
       my memory cards). It then re-writes them, makes them executable, and
       calls them to create those enfused pictures. If this script encounters
       any non-enfuse scripts, it will happily attempt to rewrite them anyway.

       Tasks accomplished by this script-rewriting operation are:

           * Replacing the original names of the files in the script with their
             new names, as determined in the second step, above.
           * Extending the script by adding lines causing the script to take
             the TIFF output of the enfuse operation and re-encode it to HQ
             JPEG, then copying the EXIF metadata from the base (non-shifted)
             photo that begins the series into that resulting JPEG. (I take it
             that it's better to have SOME EXIF DATA than none; even if not
             quite all the metadata from the base photo applies, it's the
             closest available and is mostly a fair representation of the
             actual situation at the time.)
           * Moving the shots that were components of HDR tonemaps into a
             separate HDR_components folder.

That's it. That's all it does. Current limitations include:
    * It doesn't do anything with non-JPEG images. No PNG, TIFF, BMP, RAW, etc.
    * It only operates on the current working directory.
    * It doesn't process any Magic Lantern scripts other than the enfuse/
      enfuse+align scripts. (ARE there others?)
    * It doesn't add the -d or -i (or -x, -y, or -z; or -C) options to the
      align line in the script, but maybe it should.

Currently, it depends (directly itself, or indirectly by virtue of the scripts
it writes) on these external programs:

    program             Debian package name     My version
    -------             -------------------     ----------
    align_image_stack   enfuse                  4.1.3+dfsg-2
    convert             imagemagick             8:6.8.9.9-5
    enfuse              enfuse                  4.1.3+dfsg-2
    exiftool            libimage-exiftool-perl  9.74-1
    exiftran            exiftran                2.09-1+b1

Other versions will often, though not necessarily always, work just fine.
YMMV. Remember that Ubuntu is not Debian and package names may be different.
Synaptic is your friend if you're having trouble finding things.

This script can also be imported as a Python module (it requires Python 3); try
typing

    ./postprocess_photos.py --pythonhelp

in a terminal for more.

This program comes with ABSOLUTELY NO WARRANTY. Use at your own risk.

postprocess_photos.py is copyright 2015-17 by Patrick Mooney. It is free
software, and you are welcome to redistribute it under certain conditions,
according to the GNU general public license, either version 3 or (at your own
option) any later version. See the file LICENSE.md for details.
"""

import sys, subprocess, os, glob, shutil, csv, datetime, time

import exifread                     # https://github.com/ianare/exif-py; sudo pip3 install exifread

import create_HDR_script as hdr     # https://github.com/patrick-brian-mooney/personal-library/

resume_previous_run = False
debugging = False

file_name_mappings = {}.copy()              # Dictionary that maps original names to new names.

def python_help():
    python_doc = """

    If you want to use postprocess_photos.py as a Python module, you might plausibly
    do something like this in a Python 3 shell:

        import postprocess_photos as pp
        help(pp)                        # to see the documentation for the script
        pp.read_filename_mappings()     # to read in the existing file_names.csv
        pp.process_shell_scripts()

    This would read the existing filename mappings back into memory and rewrite the
    shell scripts in the directory; this might be useful, for instance, if the
    previous run of the script had been interrupted before this could be done. Note
    that, for many things the module can do, it needs to have a set of filename
    mappings in memory; this can be done by calling read_filename_mappings() to
    read an existing file_names.csv into memory, if that was created by a previous
    call to rename_photos(); if this hasn't been done yet, call rename_photos() to
    rename the photos and build the mappings.

    There are some utility functions available that are never called by the script
    when it is merely invoked from the shell; they are available to be called by you
    from the Python shell once the module has been imported, though. These are
    currently:

        spring_forward():           if you forgot about DST before taking photos
        fall_back():                if you forgot about DST before photographing
        read_filename_mappings():   if you need to reload these to resume
        restore_file_names():       if you need to undo the auto-renaming

    Try running

        help(PROCEDURE_NAME)

    from the Python interpreter for more info on these; e.g., if you imported
    the module with

        import postprocess_photos as pp

    (as in the example above), you might try

        help(pp.fall_back)

    You can also try help(pp) or help(postprocess_photos) for complete docs, or
    dir(pp) or dir(postprocess_photos) to inspect the module.

    """
    print(python_doc)


def print_usage():
    "Display a message explaining the usage of the script."
    print(__doc__)

def spring_forward():
    """Adjust the EXIF timestamps on the batch of photos in this directory by
    adding one hour to them, as if I had forgotten to do this after the DST
    change. This routine DOES NOT require that you have previously read a set
    of file name mappings into memory; it just operates on all JPEG files in
    the current directory.
    """
    subprocess.call('exiftool "-alldates+=1:00:00" "-FileModifyDate+=1:00:00" -overwrite_original *jpg *JPG', shell=True)

def fall_back():
    """Adjust the EXIF timestamps on the batch of photos in this directory by
    subtracting one hour from them, as if I had forgotten to do this after the
    DST change. This routine DOES NOT require that you have previously read a
    set of file name mappings into memory; it just operates on all JPEG files
    in the current directory.
    """
    subprocess.call('exiftool "-alldates-=1:00:00" "-FileModifyDate-=1:00:00" -overwrite_original *jpg *JPG', shell=True)

def empty_thumbnails():
    """Create an empty .thumbnails directory and make it writable for no one.
    This routine DOES NOT REQUIRE having previously read in a set of filename
    mappings; it just operates on the current directory.
    """
    print("Keeping directory's .thumbnails subdirectory empty ... ", end='')
    try:
        if os.path.exists('.thumbnails'):
            if os.path.isdir('.thumbnails'):
                shutil.rmtree('.thumbnails')
            else:
                os.unlink('.thumbnails')
        # OK, now create the directory and make it writable for no one
        os.mkdir('.thumbnails')
        os.chmod('.thumbnails', 0o555)
    except:
        print('\n') # If an error occurs, end the status line that's waiting to be ended before letting the error propagate.
        raise
    print(' ... done.\n\n')

def rename_photos():
    """Auto-rename files based on the time when they were taken. This routine
    DOES NOT REQUIRE that a set of filename mappings be read into memory;
    instead, it creates that set of mappings and writes it to the current
    directory as file_names.csv.

    Starts by reading the date and time from each image, ideally from the EXIF
    info, but trying to extract it from the filename if this fails.

    Keeps a list as file_list: [dateTime, file_name], then converts it into another
    list, file_name_mappings: [originalName, newName].
    """
    print('Renaming photos (based on EXIF data, where possible) ... ')
    try:
        file_list = [].copy()
        for which_image in glob.glob('*jpg') + glob.glob('*JPG'):
            f = open(which_image, 'rb')
            tags = exifread.process_file(f, details=False)    # details=False means don't parse thumbnails or other slow data we don't need.
            try:
                dt = tags['EXIF DateTimeOriginal'].values
            except KeyError:
                try:
                    dt = tags['Image DateTime'].values
                except KeyError:            # Sigh. Not all of my image-generating devices generate EXIF info in all circumstances.
                    dt = which_image        # At this point, just guess based on filename.
            dt = ''.join([char for char in dt if char.isdigit()])
            dt = dt.ljust(14)   # Even if it's just gibberish, make sure it's long enough gibberish
            datetime_string = '%s-%s-%s_%s_%s_%s.jpg' % (dt[0:4], dt[4:6], dt[6:8], dt[8:10], dt[10:12], dt[12:14])
            file_list.append([datetime_string, which_image])
            f.close()

        # OK, now sort that list (twice). First, sort by original filename (globbing filenames does not preserve this). Then, sort again by
        # datetime string. Since Python sorts are stable, the second sort will preserve the order of the first when values for the sort-by
        # key for the second sort are identical.
        file_list.sort(key=lambda item: item[1])
        file_list.sort(key=lambda item: item[0])

        # Finally, actually rename the files, keeping a dictionary that maps the original to the new names.
        try:
            while len(file_list) > 0:
                which_file = file_list.pop(0)
                fname, f_ext = os.path.splitext(which_file[0])
                index = 0
                while which_file != []:
                    if index > 0:
                        the_name = '%s_%d%s' % (fname, index, f_ext)
                    else:
                        the_name = which_file[0]
                    if os.path.exists(the_name):
                        index += 1          # Bump the counter and try again
                    else:
                        os.rename(which_file[1], the_name)
                        if os.path.exists(which_file[1] + '.json'):    # To support .json files included with G+ Photos.
                            os.rename(which_file[1] + '.json', os.path.splitext(the_name)[0] + '.json')
                        file_name_mappings[which_file[1]] = the_name
                        which_file = []     # Signal we're done with this item if successful
        finally:
            # write the list to disk
            with open('file_names.csv', 'w') as file_names:
                writer = csv.writer(file_names)
                writer.writerow(['original name', 'new name'])
                rows = [[name, file_name_mappings[name]] for name in file_name_mappings]
                writer.writerows(rows)
    except:
        print('\n') # If an error occurs, end the status line that's waiting to be ended before letting the error propagate.
        raise
    print('     ... done.\n\n')

def read_filename_mappings():
    """Read file_names.csv back into memory. Do this before restoring original
    file names, or before doing other things that require a set of filename
    mappings to be in memory.
    """
    global file_name_mappings
    with open('file_names.csv') as infile:
        reader = csv.reader(infile)
        file_name_mappings = {rows[0]:rows[1] for rows in reader}

def restore_file_names():
    """Restore original file names, based on the dictionary in memory, which is
    assumed to be comprehensive and intact. This routine REQUIRES that a set of
    filename mappings is already in memory; this can be accomplished by calling
    read_filename_mappings() to read an existing file_names.csv file into
    memory.
    """
    for original_name in file_name_mappings:
        if os.path.exists(file_name_mappings[original_name]):
            print('Renaming "%s" to "%s".' % (file_name_mappings[original_name], original_name))
            os.rename(file_name_mappings[original_name], original_name)

def rotate_photos():
    """Auto-rotate all photos using exiftran. DOES NOT REQUIRE that a set of
    filename mappings be in memory; it just operates on the JPEG files in the
    current folder.
    """
    print('Auto-rotating images ...\n\n')
    subprocess.call('exiftran -aigp *jpg *JPG', shell=True)

def process_shell_scripts():
    """Rewrite any shell scripts created by MagicLantern.

    Currently, we only process HDR_????.SH scripts, which call enfuse. They MAY
    (well ... should) call align_image_stack first, but that depends on whether I
    remembered to choose 'align + enfuse" in Magic Lantern. Currently, up to two
    changes are made: old file names are replaced with their new file name
    equivalents, and (optionally) output is made TIFF instead of JPEG. This part of
    the script is currently heavily dependent on the structure of these Magic
    Lantern scripts (currently, they're produced by Magic Lantern firmware version
    1.0.2-ml-v2.3). In any case, this procedure creates identical output scripts
    whether or not the input script includes the align step.

    This routine REQUIRES that a set of filename mappings have already been read
    into memory; you can accomplish this by calling read_filename_mappings() to read
    an existing file_names.csv file into memory.
    """

    print('\nRewriting enfuse HDR scripts ... ')
    try:
        for which_script in glob.glob('HDR*SH'):
            print('    Rewriting %s' % which_script)
            old_perms = os.stat(which_script).st_mode
            with open(which_script, 'r') as the_script:
                script_lines = the_script.readlines()
                if script_lines[4].startswith('align_image_stack'):         # It's an align-first script, with 8 lines, 5 non-blank.
                    # Getting the script filenames takes some processing time here. It assumes a familiarity with the format of this line in ML firmware
                    # version 1.0.2-ml-v2.3, which currently looks like this:
                    #
                    #    align_image_stack -m -a OUTPUT_PREFIX INFILE1.JPG INFILE2.JPG [...]

                    # The number of infiles depends, of course, on settings that were in effect when the sequence was taken.
                    #
                    # So, the align_line, when tokenized, is, by array index:
                    #   [0] executable name
                    #   [1] -m, a switch meaning "optimize field of view for all images except for the first."
                    #   [2 and 3] -a OUTPUT_PREFIX specifies the prefix for all of the output files.
                    #   [4 to end] the names of the input files.
                    HDR_input_files = [file_name_mappings[which_file] if which_file in file_name_mappings
                                       else which_file
                                       for which_file in script_lines[4].split()[4:]]
                else:                                                       # It's a just-call-enfuse script, with 6 lines, 3 non-blank.
                    new_script = script_lines[:-1]                          # preserve the opening of the script as-is; we're only altering the last line.
                    last_line_tokens = script_lines[-1].split()             # FIXME: incorporate logic from branch above here to produce better final output.
                    HDR_input_files = [file_name_mappings[which_file] if which_file in file_name_mappings
                                       else which_file
                                       for which_file in last_line_tokens[3:]]
            hdr.create_script_from_file_list(HDR_input_files, file_to_move=which_script)
    except:
        print() # If an error occurs, end the line that's waiting to be ended before letting the error propagate.
        raise
    print('\n ... done rewriting enfuse scripts.\n')

def run_shell_scripts():
    """Run the executable shell scripts in the current directory. Make them non-
    executable after they have been run.

    This routine DOES NOT REQUIRE that filename mappings have been read into
    memory; it just runs all the executable shell scripts in the current
    directory.
    """
    try:
        os.mkdir('HDR_components')
        print("\nHDR_components/ directory created.")
    except FileExistsError: pass                                            # target directory already exists? Cool!
    print("Running executable scripts in %s ..." % os.getcwd())
    file_list = sorted([which_script for which_script in glob.glob("*SH") if os.access(which_script, os.X_OK)])
    for which_script in file_list:
        print('\n\n    Running script: %s' % which_script)
        subprocess.call('./' + which_script)
        os.system('chmod a-x -R %s' % which_script)
    print("\n\n ... done running scripts.")

def hang_around():
    """Offers to hang around, monitoring for executable shell scripts in the
    directory and running them if they appear. This might be handy if, for
    instance, all of the shell scripts had been accidentally deleted: this
    script can be left running while the files in the directory are manually
    examined and new shell scripts are created (perhaps by running
    create_HDR_script.py). Note that this will have to be interrupted with Ctrl+C;
    it will otherwise just run forever, waiting.

    This routine DOES NOT REQUIRE that filename mappings have been read into
    memory; it just runs all the executable shell scripts in the current
    directory.
    """
    while True:
        print('Looking for executable shell scripts at %s...' % (datetime.datetime.now().isoformat()))
        file_list = [which_script for which_script in glob.glob("*SH") if os.access(which_script, os.X_OK, effective_ids=True)]
        if len(file_list) > 0:
            print('Found %d script(s); executing ...' % len(file_list))
            run_shell_scripts()
        else:
            time.sleep(30)

# OK, let's go
if __name__ == "__main__":
    if len(sys.argv) > 1:
        if sys.argv[1] == '--help' or sys.argv[1] == '-h':
            print_usage()
            sys.exit(0)
        elif sys.argv[1] == '--pythonhelp':
            python_help()
            sys.exit(0)
        else:               # There should be no command-line arguments other than those we just processed.
            print_usage()
            sys.exit(1)

    if input('\nDo you want to postprocess the directory %s?  ' % os.getcwd())[0].lower() != 'y':
        print('\n\nREMEMBER: this script only works on the current working directory.\n')
        sys.exit(1)

    if not resume_previous_run:     # Indent/outdent the following lines to get various things skipped when resuming.
        empty_thumbnails()
        rename_photos()
        rotate_photos()
    process_shell_scripts()
    run_shell_scripts()
    if input("Want me to hang around and run scripts that show up? (Say NO if unsure.) --|  ").strip().lower()[0] == "y":
        print('\n\nOK, hit ctrl-C when finished.\n')
        hang_around()

# We're done!
